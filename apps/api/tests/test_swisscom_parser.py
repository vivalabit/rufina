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
from app.services.parsers.companies.swisscom import (
    SwisscomJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Platform Engineer {index}",
        "externalPath": f"/job/Zurich/Platform-Engineer-{index}_R-{index:07d}",
        "locationsText": "2 Locations",
        "postedOn": "Posted 2 Days Ago",
        "remoteType": "80-100%",
        "bulletFields": [f"R-{index:07d}"],
    }


def detail_payload(index: int) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": f"Senior Platform Engineer {index}",
            "jobDescription": (
                "<h2>Your skills</h2><ul><li>Python &amp; cloud</li>"
                "<li>German and English</li></ul>"
            ),
            "location": "Zurich",
            "additionalLocations": ["Bern"],
            "startDate": "2026-07-31",
            "timeType": "Full time",
            "remoteType": "80-100%",
            "externalUrl": (
                "https://swisscom.example.test/SwisscomExternalCareers/"
                f"job/Zurich/Platform-Engineer-{index}_R-{index:07d}"
            ),
        },
        "hiringOrganization": {"name": "Swisscom (Schweiz) AG"},
    }


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, []),
        (1, [0]),
        (20, [0]),
        (21, [0, 20]),
        (83, [0, 20, 40, 60, 80]),
    ],
)
def test_page_offsets_stops_on_page_containing_last_job(
    total: int,
    expected: list[int],
) -> None:
    assert page_offsets(total) == expected


def test_swisscom_parser_fetches_every_twenty_job_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(45)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
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
            index = int(request.url.path.split("Platform-Engineer-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = SwisscomJobsParser(
        base_url=(
            "https://swisscom.example.test/en-US/SwisscomExternalCareers"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=5))

    assert listing_offsets == [0, 20, 40]
    assert len(detail_requests) == 45
    assert result.status == "completed"
    assert result.search_url.endswith("/en-US/SwisscomExternalCareers")
    assert result.message == "Scanned 45 Swisscom vacancies across 3 Workday pages"
    assert len(result.jobs) == 45
    first = result.jobs[0]
    assert first.source == "swisscom"
    assert first.title == "Senior Platform Engineer 0"
    assert first.company == "Swisscom (Schweiz) AG"
    assert first.location == "Zurich, Bern"
    assert first.posted_at == "2026-07-31"
    assert first.employment_type == "Full time, 80-100%"
    assert first.description == "Your skills\nPython & cloud\nGerman and English"
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 45


def test_swisscom_parser_keeps_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [listing_record(7)]},
            )
        return httpx.Response(503)

    parser = SwisscomJobsParser(
        base_url="https://swisscom.example.test/en-US/SwisscomExternalCareers",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Platform Engineer 7"
    assert result.jobs[0].location == "Zurich"
    assert result.jobs[0].employment_type == "80-100%"
    assert result.jobs[0].raw["detail_error"]


def test_swisscom_parser_rejects_invalid_workday_payload() -> None:
    parser = SwisscomJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 4, "jobPostings": {}})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        parser.search(LinkedInSearchRequest())


def test_swisscom_parser_does_not_silently_truncate_above_page_limit() -> None:
    parser = SwisscomJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 41, "jobPostings": [listing_record(1)]},
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_swisscom_is_registered_as_a_direct_company_source() -> None:
    runner = create_vacancy_search_runner(Settings())

    assert isinstance(runner.parsers["swisscom"], SwisscomJobsParser)
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Swisscom", "filters": {}},
            "sources": ["swisscom", "swisscom"],
        }
    )
    assert request.sources == ["swisscom"]


def test_swisscom_jobs_render_as_direct_company_imports() -> None:
    parser = SwisscomJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)

    stored = parsed_job_to_stored_job(
        job,
        job_id="swisscom-r-0000001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Swisscom import"
