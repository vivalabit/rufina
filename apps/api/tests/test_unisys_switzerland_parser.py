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
from app.services.parsers.companies.unisys_switzerland import (
    SWITZERLAND_COUNTRY_FACET,
    UnisysSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(index: int) -> dict[str, object]:
    req_id = f"REQ{573100 + index}"
    return {
        "title": f"Unisys Software Engineer {index}",
        "externalPath": (f"/job/Wabern-Bern-Switzerland/Unisys-Software-Engineer-{index}_{req_id}"),
        "locationsText": "Wabern-Bern, Switzerland",
        "postedOn": "Posted 5 Days Ago",
        "jobDescription": (
            "<p><b>What success looks like</b></p><ul><li>Build reliable software.</li></ul>"
        ),
        "bulletFields": [req_id],
    }


def listing_response(
    records: list[dict[str, object]],
    total: int,
    *,
    country_id: str = SWITZERLAND_COUNTRY_FACET,
) -> dict[str, object]:
    return {
        "total": total,
        "jobPostings": records,
        "facets": [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locationCountry",
                        "descriptor": "Country",
                        "values": [
                            {
                                "descriptor": "Switzerland",
                                "id": country_id,
                                "count": total,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def detail_response(
    record: dict[str, object],
    *,
    country: str = "Switzerland",
) -> dict[str, object]:
    path = str(record["externalPath"])
    req_id = str(record["bulletFields"][0])  # type: ignore[index]
    country_data = {
        "descriptor": country,
        "id": SWITZERLAND_COUNTRY_FACET if country == "Switzerland" else "de-id",
        "alpha2Code": "CH" if country == "Switzerland" else "DE",
    }
    return {
        "jobPostingInfo": {
            "id": f"internal-{req_id}",
            "title": record["title"],
            "jobDescription": (
                "<p><b>What success looks like</b></p>"
                "<ul><li>Build reliable software.</li><li>Support clients.</li></ul>"
            ),
            "location": "Wabern-Bern, Switzerland",
            "postedOn": "Posted 5 Days Ago",
            "startDate": "2026-08-13",
            "timeType": "Full time",
            "jobReqId": req_id,
            "jobPostingId": path.rsplit("/", maxsplit=1)[-1],
            "jobPostingSiteId": "External",
            "country": country_data,
            "canApply": True,
            "posted": True,
            "jobRequisitionLocation": {
                "descriptor": "Multi-Client Switzerland-Bern",
                "country": country_data,
            },
            "externalUrl": f"https://unisys.test/External{path}",
        },
        "hiringOrganization": {
            "name": "630 Unisys (Schweiz) GmbH",
            "url": "",
        },
    }


def parser_with(
    transport: httpx.BaseTransport,
    **kwargs: object,
) -> UnisysSwitzerlandJobsParser:
    return UnisysSwitzerlandJobsParser(
        base_url=(f"https://unisys.test/External?locationCountry={SWITZERLAND_COUNTRY_FACET}"),
        detail_workers=1,
        transport=transport,
        **kwargs,
    )


def test_unisys_switzerland_scans_every_page_and_enriches_jobs() -> None:
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
        path = request.url.path.split("/External", maxsplit=1)[1]
        record = next(item for item in records if item["externalPath"] == path)
        return httpx.Response(200, json=detail_response(record))

    result = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert result.status == "completed"
    assert result.message == (
        "Scanned 21 verified Unisys Switzerland vacancies from 21 Workday country "
        "records across 2 page requests"
    )
    assert len(result.jobs) == 21
    listing_requests = [request for request in requests if request.url.path.endswith("/jobs")]
    detail_requests = [request for request in requests if "/External/job/" in request.url.path]
    assert len(detail_requests) == 21
    assert [json.loads(request.content)["offset"] for request in listing_requests] == [0, 20]
    assert json.loads(listing_requests[0].content) == {
        "appliedFacets": {"locationCountry": [SWITZERLAND_COUNTRY_FACET]},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    assert listing_requests[0].headers["origin"] == "https://unisys.test"

    first = result.jobs[0]
    assert first.source == "unisys_switzerland"
    assert first.title == "Unisys Software Engineer 0"
    assert first.company == "Unisys"
    assert first.location == "Wabern-Bern, Switzerland"
    assert first.url == (
        "https://unisys.test/External/job/Wabern-Bern-Switzerland/"
        "Unisys-Software-Engineer-0_REQ573100"
    )
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-13"
    assert first.employment_type == "Full time"
    assert first.description == (
        "What success looks like\n- Build reliable software.\n- Support clients."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 21
    assert first.raw["detail"]["jobPostingInfo"]["jobReqId"] == "REQ573100"
    assert result.jobs[-1].raw["listing_offset"] == 20


def test_unisys_switzerland_preserves_complete_listing_when_detail_fails() -> None:
    record = vacancy(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    job = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Wabern-Bern, Switzerland"
    assert job.posted_at == "Posted 5 Days Ago"
    assert job.description == "What success looks like\n- Build reliable software."
    assert "503 Service Unavailable" in job.raw["detail_error"]


def test_unisys_switzerland_keeps_only_swiss_additional_locations() -> None:
    record = vacancy(1)
    record["locationsText"] = "3 Locations"
    detail = detail_response(record, country="Germany")
    posting_info = detail["jobPostingInfo"]
    assert isinstance(posting_info, dict)
    posting_info["additionalLocations"] = [
        "Wabern-Bern, Switzerland",
        "Frankfurt, Germany",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail)

    job = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Wabern-Bern, Switzerland"
    assert "Frankfurt" not in job.location


def test_unisys_switzerland_reconciles_a_shifted_catalog() -> None:
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
        path = request.url.path.split("/External", maxsplit=1)[1]
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
def test_unisys_switzerland_rejects_invalid_catalogs(
    payload: object,
    match: str,
) -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser.search(LinkedInSearchRequest())


def test_unisys_switzerland_requires_verified_country_facet() -> None:
    record = vacancy(1)
    parser = parser_with(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_response([record], 1, country_id="foreign-id"),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="verified country facet"):
        parser.search(LinkedInSearchRequest())


def test_unisys_switzerland_rejects_duplicates_after_catalog_passes() -> None:
    record = vacancy(1)
    parser = parser_with(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response([record, record], 2))
        ),
        max_catalog_passes=2,
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        parser.search(LinkedInSearchRequest())


def test_unisys_switzerland_enforces_page_limit() -> None:
    records = [vacancy(index) for index in range(20)]
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing_response(records, 21))),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_unisys_switzerland_preserves_listing_when_detail_is_foreign() -> None:
    record = vacancy(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail_response(record, country="Germany"))

    job = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs[0]

    assert "detail" not in job.raw
    assert "incomplete or mismatched" in job.raw["detail_error"]
    assert job.location == "Wabern-Bern, Switzerland"


def test_unisys_switzerland_wraps_workday_failures() -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable")))

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_unisys_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["unisys_switzerland"]
    assert isinstance(parser, UnisysSwitzerlandJobsParser)
    assert parser.base_url == settings.unisys_switzerland_jobs_base_url
    assert parser.max_pages == settings.unisys_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.unisys_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.unisys_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Unisys Switzerland", "filters": {}},
            "sources": ["unisys_switzerland", "unisys_switzerland"],
        }
    )
    assert request.sources == ["unisys_switzerland"]


def test_unisys_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = UnisysSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="unisys_switzerland-REQ573101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Unisys Switzerland import"
    assert stored["company"] == "Unisys"
    assert stored["id"] == "unisys_switzerland-REQ573101"
