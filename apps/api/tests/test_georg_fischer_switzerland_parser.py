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
from app.services.parsers.companies.georg_fischer_switzerland import (
    SWITZERLAND_COUNTRY_FACET,
    GeorgFischerSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Process Engineer {index}",
        "externalPath": f"/job/Schaffhausen/Process-Engineer-{index}_JR{index:05d}",
        "locationsText": "Schaffhausen",
        "postedOn": "Posted 4 Days Ago",
        "bulletFields": [f"JR{index:05d}"],
    }


def detail_payload(
    index: int,
    *,
    country_id: str = SWITZERLAND_COUNTRY_FACET,
    country_name: str = "Switzerland",
    alpha2: str = "CH",
) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": f"Senior Process Engineer {index}",
            "jobDescription": (
                "<h2>The role</h2><p>Build sustainable flow systems.</p>"
                "<ul><li>Lead projects</li><li>Improve processes</li></ul>"
            ),
            "location": "Schaffhausen",
            "startDate": "2026-08-07",
            "timeType": "Full time",
            "jobReqId": f"JR{index:05d}",
            "country": {"descriptor": country_name, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "Schaffhausen IIFS",
                "country": {
                    "descriptor": country_name,
                    "id": country_id,
                    "alpha2Code": alpha2,
                },
            },
            "externalUrl": (
                "https://georgfischer.example.test/GeorgFischer_Careers/job/"
                f"Schaffhausen/Process-Engineer-{index}_JR{index:05d}"
            ),
        },
        "hiringOrganization": {"name": "Georg Fischer Rohrleitungssysteme AG"},
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


def test_georg_fischer_fetches_every_swiss_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(21)]
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
                    "total": len(records) if offset == 0 else 0,
                    "jobPostings": records[offset : offset + 20],
                },
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Process-Engineer-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = GeorgFischerSwitzerlandJobsParser(
        base_url=(
            "https://georgfischer.example.test/GeorgFischer_Careers?"
            f"locationCountry={SWITZERLAND_COUNTRY_FACET}"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20]
    assert len(detail_requests) == 21
    assert result.status == "completed"
    assert result.message == (
        "Scanned 21 verified Georg Fischer Switzerland vacancies from 21 "
        "Workday facet records across 2 page requests"
    )
    assert len(result.jobs) == 21
    first = result.jobs[0]
    assert first.source == "georg_fischer_switzerland"
    assert first.title == "Senior Process Engineer 0"
    assert first.company == "Georg Fischer Rohrleitungssysteme AG"
    assert first.location == "Schaffhausen"
    assert first.url.endswith("/Process-Engineer-0_JR00000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full time"
    assert first.description == (
        "The role\nBuild sustainable flow systems.\n- Lead projects\n- Improve processes"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 21


def test_georg_fischer_removes_foreign_record_leaked_by_country_facet() -> None:
    swiss = listing_record(1)
    foreign = listing_record(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 2, "jobPostings": [swiss, foreign]},
            )
        index = int(request.url.path.split("Process-Engineer-")[1].split("_")[0])
        if index == 2:
            return httpx.Response(
                200,
                json=detail_payload(
                    2,
                    country_id="germany-id",
                    country_name="Germany",
                    alpha2="DE",
                ),
            )
        return httpx.Response(200, json=detail_payload(1))

    result = GeorgFischerSwitzerlandJobsParser(
        base_url="https://georgfischer.example.test/GeorgFischer_Careers",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["Senior Process Engineer 1"]
    assert "from 2 Workday facet records" in result.message


def test_georg_fischer_preserves_facet_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [listing_record(7)]},
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        GeorgFischerSwitzerlandJobsParser(
            base_url="https://georgfischer.example.test/GeorgFischer_Careers",
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Process Engineer 7"
    assert job.company == "Georg Fischer"
    assert job.location == "Schaffhausen"
    assert job.url.endswith("/Process-Engineer-7_JR00007")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_georg_fischer_rejects_invalid_or_unsafe_workday_payload() -> None:
    invalid = GeorgFischerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    unsafe = GeorgFischerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total": 1,
                    "jobPostings": [
                        {
                            "title": "Engineer",
                            "externalPath": "https://evil.example/job/Engineer/1",
                        }
                    ],
                },
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="unsafe vacancy path"):
        unsafe.search(LinkedInSearchRequest())


def test_georg_fischer_rejects_truncated_or_oversized_catalog() -> None:
    truncated = GeorgFischerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 2, "jobPostings": [listing_record(1)]},
            )
        )
    )
    oversized = GeorgFischerSwitzerlandJobsParser(
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

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_georg_fischer_wraps_listing_request_failures() -> None:
    parser = GeorgFischerSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_georg_fischer_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["georg_fischer_switzerland"]
    assert isinstance(parser, GeorgFischerSwitzerlandJobsParser)
    assert parser.base_url == settings.georg_fischer_switzerland_jobs_base_url
    assert parser.max_pages == settings.georg_fischer_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.georg_fischer_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Georg Fischer Switzerland", "filters": {}},
            "sources": ["georg_fischer_switzerland", "georg_fischer_switzerland"],
        }
    )
    assert request.sources == ["georg_fischer_switzerland"]


def test_georg_fischer_jobs_render_as_direct_company_imports() -> None:
    parser = GeorgFischerSwitzerlandJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="georg_fischer_switzerland-jr00001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Georg Fischer Switzerland import"
    assert stored["id"] == "georg_fischer_switzerland-jr00001"
