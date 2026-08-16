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
from app.services.parsers.companies.julius_baer_switzerland import (
    SWITZERLAND_COUNTRY_FACET,
    JuliusBaerSwitzerlandJobsParser,
    is_swiss_record,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Senior Software Engineer {index} 80-100% (f/m/d)",
        "externalPath": (
            f"/job/Zurich/Senior-Software-Engineer-{index}-80-100---f-m-d-"
            f"_r-{19000 + index}-1"
        ),
        "locationsText": "Zurich",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": [f"r-{19000 + index}"],
    }


def detail_payload(
    index: int,
    *,
    country_id: str = SWITZERLAND_COUNTRY_FACET,
    country_name: str = "Switzerland",
) -> dict[str, object]:
    record = listing_record(index)
    path = str(record["externalPath"])
    return {
        "jobPostingInfo": {
            "id": f"posting-{index}",
            "title": record["title"],
            "jobDescription": (
                "<h2>Your challenge</h2><p>Build secure banking systems.</p>"
                "<ul><li>Lead delivery</li><li>Improve platforms</li></ul>"
            ),
            "location": "Zurich",
            "postedOn": "Posted 2 Days Ago",
            "startDate": "2026-08-13",
            "timeType": "Full time",
            "jobReqId": f"r-{19000 + index}",
            "country": {"descriptor": country_name, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "Zurich",
                "country": {
                    "descriptor": country_name,
                    "id": country_id,
                    "alpha2Code": "CH" if country_name == "Switzerland" else "DE",
                },
            },
            "externalUrl": (
                "https://juliusbaer.wd3.myworkdayjobs.com/External" + path
            ),
        },
        "hiringOrganization": {
            "name": "CH10 - BJB Bank Julius Baer & Co. Ltd."
        },
    }


@pytest.mark.parametrize(
    ("total", "expected"),
    [(0, []), (1, [0]), (20, [0]), (21, [0, 20]), (45, [0, 20, 40])],
)
def test_page_offsets_stops_on_page_containing_last_job(
    total: int,
    expected: list[int],
) -> None:
    assert page_offsets(total) == expected


def test_julius_baer_fetches_complete_swiss_catalog_and_details() -> None:
    records = [listing_record(index) for index in range(45)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            assert body["appliedFacets"] == {
                "Location_Country": [SWITZERLAND_COUNTRY_FACET]
            }
            assert body["limit"] == 20
            assert body["searchText"] == ""
            offset = body["offset"]
            listing_offsets.append(offset)
            return httpx.Response(
                200,
                json={
                    "total": len(records) if offset == 0 else 0,
                    "jobPostings": records[offset : offset + 20],
                },
                request=request,
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Engineer-")[1].split("-")[0])
            return httpx.Response(200, json=detail_payload(index), request=request)
        return httpx.Response(404, request=request)

    result = JuliusBaerSwitzerlandJobsParser(
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20, 40]
    assert len(detail_requests) == 45
    assert result.message == (
        "Scanned 45 verified Julius Baer Switzerland vacancies from 45 Workday "
        "facet records across 3 page requests"
    )
    assert len(result.jobs) == 45
    job = result.jobs[0]
    assert job.source == "julius_baer_switzerland"
    assert job.title == "Senior Software Engineer 0 80-100% (f/m/d)"
    assert job.company == "Julius Baer"
    assert job.location == "Zurich"
    assert job.url == (
        "https://juliusbaer.wd3.myworkdayjobs.com/External/job/Zurich/"
        "Senior-Software-Engineer-0-80-100---f-m-d-_r-19000-1"
    )
    assert job.apply_url == job.url
    assert job.posted_at == "2026-08-13"
    assert job.employment_type == "Full time"
    assert job.description == (
        "Your challenge\nBuild secure banking systems.\n- Lead delivery\n"
        "- Improve platforms"
    )
    assert job.raw["listing_offset"] == 0
    assert job.raw["total_available"] == 45


def test_julius_baer_removes_foreign_records_leaked_by_country_facet() -> None:
    swiss = listing_record(1)
    foreign = listing_record(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 2, "jobPostings": [swiss, foreign]},
                request=request,
            )
        index = 2 if "Engineer-2-" in request.url.path else 1
        payload = (
            detail_payload(index, country_id="germany-id", country_name="Germany")
            if index == 2
            else detail_payload(index)
        )
        return httpx.Response(200, json=payload, request=request)

    result = JuliusBaerSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == [
        "Senior Software Engineer 1 80-100% (f/m/d)"
    ]
    assert "from 2 Workday facet records" in result.message


def test_julius_baer_rejects_mismatched_detail_identity() -> None:
    record = listing_record(1)
    payload = detail_payload(1)
    payload["jobPostingInfo"]["jobReqId"] = "r-evil"  # type: ignore[index]

    assert not is_swiss_record({**record, "detail": payload})


def test_julius_baer_preserves_listing_when_detail_request_fails() -> None:
    record = listing_record(7)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [record]},
                request=request,
            )
        return httpx.Response(503, text="temporarily unavailable", request=request)

    job = JuliusBaerSwitzerlandJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Senior Software Engineer 7 80-100% (f/m/d)"
    assert job.company == "Julius Baer"
    assert job.location == "Zurich"
    assert job.url.endswith("_r-19007-1")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_julius_baer_rejects_invalid_duplicate_and_oversized_catalogs() -> None:
    invalid = JuliusBaerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"total": 1, "jobPostings": {}}, request=request
            )
        )
    )
    duplicate_record = listing_record(1)
    duplicate = JuliusBaerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "total": 2,
                    "jobPostings": [duplicate_record, duplicate_record],
                },
                request=request,
            )
        )
    )
    oversized = JuliusBaerSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "total": 21,
                    "jobPostings": [listing_record(index) for index in range(20)],
                },
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy paths"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_julius_baer_rejects_total_change_and_empty_page() -> None:
    records = [listing_record(index) for index in range(21)]

    def changed_total(request: httpx.Request) -> httpx.Response:
        offset = json.loads(request.content)["offset"]
        return httpx.Response(
            200,
            json={
                "total": 21 if offset == 0 else 22,
                "jobPostings": records[offset : offset + 20],
            },
            request=request,
        )

    def empty_page(request: httpx.Request) -> httpx.Response:
        offset = json.loads(request.content)["offset"]
        return httpx.Response(
            200,
            json={
                "total": 21,
                "jobPostings": records[:20] if offset == 0 else [],
            },
            request=request,
        )

    with pytest.raises(DirectCompanyRequestError, match="changed its vacancy total"):
        JuliusBaerSwitzerlandJobsParser(
            transport=httpx.MockTransport(changed_total)
        ).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="unexpectedly empty"):
        JuliusBaerSwitzerlandJobsParser(
            transport=httpx.MockTransport(empty_page)
        ).search(LinkedInSearchRequest())


def test_julius_baer_wraps_listing_request_failures() -> None:
    parser = JuliusBaerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_julius_baer_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["julius_baer_switzerland"]

    assert isinstance(parser, JuliusBaerSwitzerlandJobsParser)
    assert parser.base_url == settings.julius_baer_switzerland_jobs_base_url
    assert parser.max_pages == settings.julius_baer_switzerland_jobs_max_pages
    assert (
        parser.detail_workers
        == settings.julius_baer_switzerland_jobs_detail_workers
    )
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Julius Baer", "filters": {}},
            "sources": ["julius_baer_switzerland", "julius_baer_switzerland"],
        }
    )
    assert request.sources == ["julius_baer_switzerland"]


def test_julius_baer_jobs_render_as_direct_company_imports() -> None:
    parser = JuliusBaerSwitzerlandJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="julius_baer_switzerland-r-19001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Julius Baer Switzerland import"
    assert stored["id"] == "julius_baer_switzerland-r-19001"
    assert stored["company"] == "Julius Baer"
