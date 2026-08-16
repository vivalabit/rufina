from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.biogen_switzerland import (
    SWITZERLAND_COUNTRY_FACET,
    BiogenSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(index: int, *, multi_location: bool = False) -> dict[str, object]:
    req_id = f"REQ{23000 + index}"
    location = "Research-Triangle-Park-NC" if multi_location else "Baar-Switzerland"
    return {
        "title": f"Biogen role {index}",
        "externalPath": f"/job/{location}/Biogen-role-{index}_{req_id}",
        "locationsText": "3 Locations" if multi_location else "Baar, Switzerland",
        "postedOn": "Posted 2 Days Ago",
        "remoteType": "Hybrid",
        "bulletFields": [req_id],
    }


def listing_response(
    records: list[dict[str, object]],
    total: int,
) -> dict[str, object]:
    return {
        "total": total,
        "jobPostings": records,
        "facets": [],
        "userAuthenticated": False,
    }


def detail_response(
    record: dict[str, object],
    *,
    multi_location: bool = False,
    country: str = "Switzerland",
) -> dict[str, object]:
    path = str(record["externalPath"])
    req_id = str(record["bulletFields"][0])  # type: ignore[index]
    if multi_location:
        location = "Research Triangle Park, NC"
        additional_locations = ["Baar, Switzerland", "Cambridge, MA"]
        country_data = {
            "descriptor": "United States of America",
            "id": "bc33aa3152ec42d4995f4791a106ed09",
            "alpha2Code": "US",
        }
    else:
        location = "Baar, Switzerland"
        additional_locations = []
        country_data = {
            "descriptor": country,
            "id": SWITZERLAND_COUNTRY_FACET if country == "Switzerland" else "de-id",
            "alpha2Code": "CH" if country == "Switzerland" else "DE",
        }
    return {
        "jobPostingInfo": {
            "id": f"internal-{req_id}",
            "title": record["title"],
            "jobDescription": ("<p><b>About this role</b></p><ul><li>Build therapies.</li></ul>"),
            "location": location,
            "additionalLocations": additional_locations,
            "postedOn": "Posted 2 Days Ago",
            "startDate": "2026-08-14",
            "timeType": "Full time",
            "jobReqId": req_id,
            "jobPostingSiteId": "external",
            "country": country_data,
            "canApply": True,
            "posted": True,
            "jobRequisitionLocation": {
                "descriptor": location,
                "country": country_data,
            },
            "remoteType": "Hybrid",
            "externalUrl": f"https://biibhr.test/external{path}",
        },
        "hiringOrganization": {"name": "", "url": ""},
        "similarJobs": [],
        "userAuthenticated": False,
    }


def parser_with(
    transport: httpx.BaseTransport,
    **kwargs: object,
) -> BiogenSwitzerlandJobsParser:
    return BiogenSwitzerlandJobsParser(
        base_url=(f"https://biibhr.test/external?locationCountry={SWITZERLAND_COUNTRY_FACET}"),
        detail_workers=1,
        transport=transport,
        **kwargs,
    )


def test_biogen_switzerland_scans_every_page_and_enriches_jobs() -> None:
    records = [vacancy(index) for index in range(21)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            offset = body["offset"]
            page_total = len(records) if offset == 0 else 0
            return httpx.Response(
                200,
                json=listing_response(records[offset : offset + 20], page_total),
            )
        path = request.url.path.split("/external", maxsplit=1)[1]
        record = next(item for item in records if item["externalPath"] == path)
        return httpx.Response(200, json=detail_response(record))

    result = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert result.status == "completed"
    assert result.message == (
        "Scanned 21 verified Biogen Switzerland vacancies from 21 Workday facet "
        "records across 2 page requests"
    )
    assert len(result.jobs) == 21
    listing_requests = [request for request in requests if request.url.path.endswith("/jobs")]
    detail_requests = [request for request in requests if "/external/job/" in request.url.path]
    assert len(detail_requests) == 21
    assert [json.loads(request.content)["offset"] for request in listing_requests] == [0, 20]
    first_payload = json.loads(listing_requests[0].content)
    assert first_payload == {
        "appliedFacets": {"locationCountry": [SWITZERLAND_COUNTRY_FACET]},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    assert listing_requests[0].headers["origin"] == "https://biibhr.test"

    first = result.jobs[0]
    assert first.source == "biogen_switzerland"
    assert first.title == "Biogen role 0"
    assert first.company == "Biogen"
    assert first.location == "Baar, Switzerland"
    assert first.url == "https://biibhr.test/external/job/Baar-Switzerland/Biogen-role-0_REQ23000"
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-14"
    assert first.employment_type == "Full time, Hybrid"
    assert first.description == "About this role\n- Build therapies."
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 21
    assert first.raw["detail"]["jobPostingInfo"]["jobReqId"] == "REQ23000"
    assert result.jobs[-1].raw["listing_offset"] == 20


def test_biogen_switzerland_keeps_only_swiss_multi_locations() -> None:
    record = vacancy(1, multi_location=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail_response(record, multi_location=True))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs[0].location == "Baar, Switzerland"
    assert "Research Triangle Park" not in result.jobs[0].location
    assert "Cambridge" not in result.jobs[0].location


def test_biogen_switzerland_keeps_listing_when_detail_fails() -> None:
    record = vacancy(1, multi_location=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].location == "Switzerland"
    assert result.jobs[0].description is None
    assert result.jobs[0].posted_at == "Posted 2 Days Ago"
    assert "503 Service Unavailable" in result.jobs[0].raw["detail_error"]


def test_biogen_switzerland_reconciles_a_shifted_catalog() -> None:
    records = [vacancy(index) for index in range(21)]
    listing_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_calls
        if request.url.path.endswith("/jobs"):
            listing_calls += 1
            offset = json.loads(request.content)["offset"]
            page = records[offset : offset + 20]
            if listing_calls == 2:
                page = [records[19]]
            return httpx.Response(
                200,
                json=listing_response(page, len(records) if offset == 0 else 0),
            )
        path = request.url.path.split("/external", maxsplit=1)[1]
        record = next(item for item in records if item["externalPath"] == path)
        return httpx.Response(200, json=detail_response(record))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 21
    assert listing_calls == 4
    assert all(job.raw["listing_pass"] == 2 for job in result.jobs)


@pytest.mark.parametrize(
    "payload,match",
    [
        ([], "must be an object"),
        ({"total": "1", "jobPostings": []}, "invalid total"),
        ({"total": 1, "jobPostings": {}}, "invalid jobPostings"),
        ({"total": 1, "jobPostings": [{}]}, "incomplete vacancy"),
    ],
)
def test_biogen_switzerland_rejects_invalid_catalogs(
    payload: object,
    match: str,
) -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser.search(LinkedInSearchRequest())


def test_biogen_switzerland_rejects_duplicates_after_catalog_passes() -> None:
    record = vacancy(1)
    parser = parser_with(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response([record, record], 2))
        ),
        max_catalog_passes=2,
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        parser.search(LinkedInSearchRequest())


def test_biogen_switzerland_enforces_page_limit() -> None:
    records = [vacancy(index) for index in range(20)]
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing_response(records, 21))),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_biogen_switzerland_preserves_listing_when_detail_is_foreign() -> None:
    record = vacancy(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail_response(record, country="Germany"))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert "detail" not in result.jobs[0].raw
    assert "incomplete or mismatched" in result.jobs[0].raw["detail_error"]


def test_biogen_switzerland_wraps_workday_failures() -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable")))

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_biogen_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["biogen_switzerland"]
    assert isinstance(parser, BiogenSwitzerlandJobsParser)
    assert parser.base_url == settings.biogen_switzerland_jobs_base_url
    assert parser.max_pages == settings.biogen_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.biogen_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.biogen_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Biogen Switzerland", "filters": {}},
            "sources": ["biogen_switzerland", "biogen_switzerland"],
        }
    )
    assert request.sources == ["biogen_switzerland"]


def test_biogen_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = BiogenSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="biogen_switzerland-REQ23001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Biogen Switzerland import"
    assert stored["company"] == "Biogen"
