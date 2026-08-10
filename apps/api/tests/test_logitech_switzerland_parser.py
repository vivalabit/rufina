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
from app.services.parsers.companies.logitech_switzerland import (
    SWITZERLAND_COUNTRY_FACET,
    LogitechSwitzerlandJobsParser,
    is_swiss_record,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Software Engineer {index}",
        "externalPath": (f"/job/Lausanne-Switzerland/Software-Engineer-{index}_{147000 + index}"),
        "locationsText": "Lausanne, Switzerland",
        "postedOn": "Posted 2 Days Ago",
        "bulletFields": [str(147000 + index)],
    }


def detail_payload(index: int) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": f"Senior Software Engineer {index}",
            "jobDescription": (
                "<h2>The role</h2><p>Build products people love.</p>"
                "<ul><li>Lead projects</li><li>Improve systems</li></ul>"
            ),
            "location": "Lausanne, Switzerland",
            "additionalLocations": ["Cork, Ireland"],
            "startDate": "2026-08-07",
            "timeType": "Full time",
            "remoteType": "Hybrid",
            "jobReqId": str(147000 + index),
            "country": {
                "descriptor": "Switzerland",
                "id": SWITZERLAND_COUNTRY_FACET,
            },
            "jobRequisitionLocation": {
                "descriptor": "Lausanne",
                "country": {
                    "descriptor": "Switzerland",
                    "id": SWITZERLAND_COUNTRY_FACET,
                    "alpha2Code": "CH",
                },
            },
            "externalUrl": (
                "https://logitech.example.test/Logitech/job/Lausanne-Switzerland/"
                f"Software-Engineer-{index}_{147000 + index}"
            ),
        },
        "hiringOrganization": {"name": "442 LEU - Logitech Europe SA"},
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


def test_logitech_fetches_every_swiss_workday_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(45)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            assert body["appliedFacets"] == {"locationCountry": [SWITZERLAND_COUNTRY_FACET]}
            assert body["limit"] == 20
            offset = body["offset"]
            listing_offsets.append(offset)
            return httpx.Response(
                200,
                json={
                    "total": len(records),
                    "jobPostings": records[offset : offset + 20],
                },
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Software-Engineer-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = LogitechSwitzerlandJobsParser(
        base_url=(
            f"https://logitech.example.test/Logitech?locationCountry={SWITZERLAND_COUNTRY_FACET}"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20, 40]
    assert len(detail_requests) == 45
    assert result.status == "completed"
    assert result.message == (
        "Scanned 45 verified Logitech Switzerland vacancies from 45 Workday "
        "facet records across 3 page requests"
    )
    assert len(result.jobs) == 45
    first = result.jobs[0]
    assert first.source == "logitech_switzerland"
    assert first.title == "Senior Software Engineer 0"
    assert first.company == "Logitech"
    assert first.location == "Lausanne, Switzerland, Cork, Ireland"
    assert first.url.endswith("/Software-Engineer-0_147000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full time, Hybrid"
    assert first.description == (
        "The role\nBuild products people love.\nLead projects\nImprove systems"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 45


def test_logitech_removes_foreign_records_leaked_by_workday_country_facet() -> None:
    swiss = listing_record(1)
    foreign = {
        "title": "Africa Category Manager",
        "externalPath": "/job/Johannesburg-South-Africa/Africa-Category-Manager_9",
        "locationsText": "2 Locations",
        "postedOn": "Posted Today",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 2, "jobPostings": [swiss, foreign]},
            )
        if "Johannesburg" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "jobPostingInfo": {
                        "title": "Africa Category Manager",
                        "location": "Johannesburg, South Africa",
                        "additionalLocations": ["CWR EMEA Offsite"],
                        "country": {"descriptor": "South Africa", "id": "za-id"},
                    }
                },
            )
        return httpx.Response(200, json=detail_payload(1))

    result = LogitechSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert [job.title for job in result.jobs] == ["Senior Software Engineer 1"]
    assert "from 2 Workday facet records" in result.message
    assert is_swiss_record(
        {
            "detail": {
                "jobPostingInfo": {
                    "location": "London, United Kingdom",
                    "additionalLocations": ["Basel, Switzerland"],
                }
            }
        }
    )


def test_logitech_preserves_a_swiss_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [listing_record(7)]},
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = LogitechSwitzerlandJobsParser(
        base_url=(
            f"https://logitech.example.test/Logitech?locationCountry={SWITZERLAND_COUNTRY_FACET}"
        ),
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Software Engineer 7"
    assert job.company == "Logitech"
    assert job.location == "Lausanne, Switzerland"
    assert job.url.endswith("/Software-Engineer-7_147007")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_logitech_rejects_invalid_truncated_or_oversized_catalogs() -> None:
    invalid = LogitechSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    truncated = LogitechSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 2, "jobPostings": [listing_record(1)]},
            )
        )
    )
    oversized = LogitechSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total": 21,
                    "jobPostings": [listing_record(index) for index in range(20)],
                },
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_logitech_wraps_listing_request_failures() -> None:
    parser = LogitechSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_logitech_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["logitech_switzerland"]
    assert isinstance(parser, LogitechSwitzerlandJobsParser)
    assert parser.base_url == settings.logitech_switzerland_jobs_base_url
    assert parser.max_pages == settings.logitech_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.logitech_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Logitech Switzerland", "filters": {}},
            "sources": ["logitech_switzerland", "logitech_switzerland"],
        }
    )
    assert request.sources == ["logitech_switzerland"]


def test_logitech_jobs_render_as_direct_company_imports() -> None:
    parser = LogitechSwitzerlandJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="logitech_switzerland-147001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Logitech Switzerland import"
    assert stored["id"] == "logitech_switzerland-147001"
