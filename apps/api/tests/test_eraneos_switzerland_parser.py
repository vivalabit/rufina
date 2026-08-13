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
from app.services.parsers.companies.eraneos_switzerland import (
    SWITZERLAND_COUNTRY_ID,
    EraneosSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Technology Consultant {index}",
        "externalPath": f"/job/Zurich/Technology-Consultant-{index}_JR{index:05d}",
        "locationsText": "2 Locations",
        "postedOn": "Posted 4 Days Ago",
        "bulletFields": [f"JR{index:05d}"],
    }


def detail_payload(
    index: int,
    *,
    country_id: str = SWITZERLAND_COUNTRY_ID,
    country_name: str = "Switzerland",
    alpha2: str = "CH",
) -> dict[str, object]:
    return {
        "jobPostingInfo": {
            "title": f"Senior Technology Consultant {index}",
            "jobDescription": (
                "<h2>Deine Rolle</h2><p>Gestalte nachhaltige Transformationen.</p>"
                "<ul><li>Berate Kunden</li><li>Leite Projekte</li></ul>"
            ),
            "location": "Zurich",
            "additionalLocations": ["Bern"],
            "startDate": "2026-08-07",
            "timeType": "Full time",
            "jobReqId": f"JR{index:05d}",
            "country": {"descriptor": country_name, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "Zurich",
                "country": {
                    "descriptor": country_name,
                    "id": country_id,
                    "alpha2Code": alpha2,
                },
            },
            "externalUrl": (
                "https://eraneos.example.test/Eraneos_External_Career_Site/job/"
                f"Zurich/Technology-Consultant-{index}_JR{index:05d}"
            ),
        },
        "hiringOrganization": {"name": "Eraneos Switzerland AG"},
    }


@pytest.mark.parametrize(
    ("total", "expected"),
    [(0, []), (1, [0]), (20, [0]), (21, [0, 20]), (59, [0, 20, 40])],
)
def test_page_offsets_stops_on_page_containing_last_job(
    total: int,
    expected: list[int],
) -> None:
    assert page_offsets(total) == expected


def test_eraneos_fetches_every_swiss_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(21)]
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
                    "total": len(records) if offset == 0 else 0,
                    "jobPostings": records[offset : offset + 20],
                },
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Technology-Consultant-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = EraneosSwitzerlandJobsParser(
        base_url="https://eraneos.example.test/Eraneos_External_Career_Site",
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20]
    assert len(detail_requests) == 21
    assert result.status == "completed"
    assert result.message == (
        "Scanned 21 verified Eraneos Switzerland vacancies from 21 "
        "Workday site records across 2 page requests"
    )
    assert len(result.jobs) == 21
    first = result.jobs[0]
    assert first.source == "eraneos_switzerland"
    assert first.title == "Senior Technology Consultant 0"
    assert first.company == "Eraneos Switzerland AG"
    assert first.location == "Zurich, Bern"
    assert first.url.endswith("/Technology-Consultant-0_JR00000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full time"
    assert first.description == (
        "Deine Rolle\nGestalte nachhaltige Transformationen.\n- Berate Kunden\n- Leite Projekte"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 21


def test_eraneos_removes_foreign_record_leaked_by_swiss_site() -> None:
    swiss = listing_record(1)
    foreign = listing_record(2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 2, "jobPostings": [swiss, foreign]},
            )
        index = int(request.url.path.split("Technology-Consultant-")[1].split("_")[0])
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

    result = EraneosSwitzerlandJobsParser(
        base_url="https://eraneos.example.test/Eraneos_External_Career_Site",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["Senior Technology Consultant 1"]
    assert "from 2 Workday site records" in result.message


def test_eraneos_preserves_site_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": 1, "jobPostings": [listing_record(7)]},
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        EraneosSwitzerlandJobsParser(
            base_url="https://eraneos.example.test/Eraneos_External_Career_Site",
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Technology Consultant 7"
    assert job.company == "Eraneos Switzerland AG"
    assert job.location == "Zurich"
    assert job.url.endswith("/Technology-Consultant-7_JR00007")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_eraneos_rejects_invalid_or_unsafe_workday_payload() -> None:
    invalid = EraneosSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    unsafe = EraneosSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total": 1,
                    "jobPostings": [
                        {
                            "title": "Consultant",
                            "externalPath": "https://evil.example/job/Consultant/1",
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


def test_eraneos_rejects_truncated_or_oversized_catalog() -> None:
    truncated = EraneosSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 2, "jobPostings": [listing_record(1)]},
            )
        )
    )
    oversized = EraneosSwitzerlandJobsParser(
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


def test_eraneos_wraps_listing_request_failures() -> None:
    parser = EraneosSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_eraneos_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["eraneos_switzerland"]
    assert isinstance(parser, EraneosSwitzerlandJobsParser)
    assert parser.base_url == settings.eraneos_switzerland_jobs_base_url
    assert parser.max_pages == settings.eraneos_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.eraneos_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Eraneos Switzerland", "filters": {}},
            "sources": ["eraneos_switzerland", "eraneos_switzerland"],
        }
    )
    assert request.sources == ["eraneos_switzerland"]


def test_eraneos_jobs_render_as_direct_company_imports() -> None:
    parser = EraneosSwitzerlandJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="eraneos_switzerland-jr100169",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Eraneos Switzerland import"
    assert stored["id"] == "eraneos_switzerland-jr100169"
