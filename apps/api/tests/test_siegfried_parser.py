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
from app.services.parsers.companies.siegfried import (
    SiegfriedJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Process Engineer {index}",
        "externalPath": f"/job/Zofingen/Process-Engineer-{index}_R26_{index:03d}",
        "locationsText": "Zofingen",
        "remoteType": "Hybrid",
        "bulletFields": [f"R26_{index:03d}"],
    }


def detail_payload(index: int) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": f"Senior Process Engineer {index}",
            "jobDescription": (
                "<h2>Your role</h2><p>Scale pharmaceutical processes.</p>"
                "<ul><li>Lead projects</li><li>Improve quality</li></ul>"
            ),
            "location": "Zofingen",
            "startDate": "2026-08-07",
            "timeType": "Full time",
            "remoteType": "Hybrid",
            "jobReqId": f"R26_{index:03d}",
            "externalUrl": (
                "https://siegfried.example.test/external/job/Zofingen/"
                f"Process-Engineer-{index}_R26_{index:03d}"
            ),
        },
        "hiringOrganization": {"name": "Siegfried AG"},
    }


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, []),
        (1, [0]),
        (20, [0]),
        (21, [0, 20]),
        (45, [0, 20, 40]),
    ],
)
def test_page_offsets_stops_on_page_containing_last_job(
    total: int,
    expected: list[int],
) -> None:
    assert page_offsets(total) == expected


def test_siegfried_fetches_every_workday_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(45)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            assert body["appliedFacets"] == {}
            assert body["limit"] == 20
            offset = body["offset"]
            listing_offsets.append(offset)
            return httpx.Response(
                200,
                json={
                    # Siegfried's Workday API reports the catalog total only
                    # on the first page; later offsets currently return zero.
                    "total": len(records) if offset == 0 else 0,
                    "jobPostings": records[offset : offset + 20],
                },
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Process-Engineer-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = SiegfriedJobsParser(
        base_url="https://siegfried.example.test/external",
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20, 40]
    assert len(detail_requests) == 45
    assert result.status == "completed"
    assert result.message == (
        "Scanned 45 Siegfried vacancies from 45 catalog records across 3 "
        "Workday page requests"
    )
    assert len(result.jobs) == 45
    first = result.jobs[0]
    assert first.source == "siegfried"
    assert first.title == "Senior Process Engineer 0"
    assert first.company == "Siegfried AG"
    assert first.location == "Zofingen"
    assert first.url.endswith("/Process-Engineer-0_R26_000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full time, Hybrid"
    assert first.description == (
        "Your role\nScale pharmaceutical processes.\nLead projects\nImprove quality"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 45


def test_siegfried_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [listing_record(7)]},
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SiegfriedJobsParser(
        base_url="https://siegfried.example.test/external",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Process Engineer 7"
    assert job.company == "Siegfried"
    assert job.location == "Zofingen"
    assert job.url == (
        "https://siegfried.example.test/external/job/Zofingen/"
        "Process-Engineer-7_R26_007"
    )
    assert job.employment_type == "Hybrid"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_siegfried_retries_when_catalog_total_changes_during_pagination() -> None:
    records = [listing_record(index) for index in range(20)]
    listing_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            offset = body["offset"]
            listing_offsets.append(offset)
            if listing_offsets == [0]:
                return httpx.Response(
                    200,
                    json={"total": 21, "jobPostings": records},
                )
            return httpx.Response(
                200,
                json={
                    "total": 20,
                    "jobPostings": records[offset : offset + 20],
                },
            )
        return httpx.Response(503, text="detail unavailable")

    parser = SiegfriedJobsParser(
        base_url="https://siegfried.example.test/external",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20, 0]
    assert len(result.jobs) == 20
    assert {job.raw["catalog_pass"] for job in result.jobs} == {2}
    assert result.message.endswith("across 3 Workday page requests")


def test_siegfried_rejects_invalid_or_incomplete_workday_payload() -> None:
    invalid_jobs = SiegfriedJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    incomplete_job = SiegfriedJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 1, "jobPostings": [{"title": "Engineer"}]},
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid_jobs.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        incomplete_job.search(LinkedInSearchRequest())


def test_siegfried_rejects_truncated_or_oversized_catalog() -> None:
    oversized = SiegfriedJobsParser(
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
    truncated = SiegfriedJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 2, "jobPostings": [listing_record(1)]},
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())


def test_siegfried_wraps_listing_request_failures() -> None:
    parser = SiegfriedJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(503, text="temporarily unavailable")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_siegfried_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["siegfried"]
    assert isinstance(parser, SiegfriedJobsParser)
    assert parser.base_url == settings.siegfried_jobs_base_url
    assert parser.max_pages == settings.siegfried_jobs_max_pages
    assert parser.max_catalog_passes == settings.siegfried_jobs_max_catalog_passes
    assert parser.detail_workers == settings.siegfried_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Siegfried", "filters": {}},
            "sources": ["siegfried", "siegfried"],
        }
    )
    assert request.sources == ["siegfried"]


def test_siegfried_jobs_render_as_direct_company_imports() -> None:
    parser = SiegfriedJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="siegfried-r26-001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Siegfried import"
    assert stored["id"] == "siegfried-r26-001"
