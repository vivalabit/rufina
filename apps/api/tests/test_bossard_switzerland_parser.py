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
from app.services.parsers.companies.bossard_switzerland import (
    BOSSARD_ZUG_LOCATION_FACET,
    SWITZERLAND_COUNTRY_FACET,
    BossardSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Application Engineer {index} | Bossard AG",
        "externalPath": f"/job/Zug/Application-Engineer-{index}_JR{index:05d}",
        "timeType": "Full time",
        "locationsText": "Zug",
        "postedOn": "Posted Today",
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int | None = None,
    facet_id: str = BOSSARD_ZUG_LOCATION_FACET,
    facet_name: str = "Zug",
) -> dict[str, object]:
    available = len(records) if total is None else total
    return {
        "total": available,
        "jobPostings": records,
        "facets": [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locations",
                        "descriptor": "Locations",
                        "values": [
                            {
                                "descriptor": facet_name,
                                "id": facet_id,
                                "count": available,
                            }
                        ],
                    }
                ],
            }
        ],
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
            "id": f"400000000000000000000000000{index:05d}",
            "title": f"Senior Application Engineer {index} | Bossard AG",
            "jobDescription": (
                "<h2>Your mission</h2><p>Develop fastening solutions.</p>"
                "<ul><li>Advise customers</li><li>Improve products</li></ul>"
            ),
            "location": "Zug",
            "startDate": "2026-08-18",
            "timeType": "Full time",
            "country": {"descriptor": country_name, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "Zug",
                "country": {
                    "descriptor": country_name,
                    "id": country_id,
                    "alpha2Code": alpha2,
                },
            },
            "externalUrl": (
                "https://bossard.example.test/BossardJobs/job/Zug/"
                f"Application-Engineer-{index}_JR{index:05d}"
            ),
        },
        "hiringOrganization": {"name": "Bossard AG"},
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


def test_bossard_fetches_every_zug_page_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(21)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            assert body["appliedFacets"] == {"locations": [BOSSARD_ZUG_LOCATION_FACET]}
            assert body["limit"] == 20
            offset = body["offset"]
            listing_offsets.append(offset)
            payload = listing_payload(
                records[offset : offset + 20],
                total=len(records) if offset == 0 else 0,
            )
            return httpx.Response(200, json=payload)
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            index = int(request.url.path.split("Application-Engineer-")[1].split("_")[0])
            return httpx.Response(200, json=detail_payload(index))
        return httpx.Response(404)

    parser = BossardSwitzerlandJobsParser(
        base_url=(
            f"https://bossard.example.test/BossardJobs?locations={BOSSARD_ZUG_LOCATION_FACET}"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20]
    assert len(detail_requests) == 21
    assert result.status == "completed"
    assert result.message == (
        "Scanned 21 verified Bossard Switzerland vacancies from 21 Workday "
        "Zug facet records across 2 page requests"
    )
    assert len(result.jobs) == 21
    first = result.jobs[0]
    assert first.source == "bossard_switzerland"
    assert first.title == "Senior Application Engineer 0 | Bossard AG"
    assert first.company == "Bossard AG"
    assert first.location == "Zug"
    assert first.url.endswith("/Application-Engineer-0_JR00000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-18"
    assert first.employment_type == "Full time"
    assert first.description == (
        "Your mission\nDevelop fastening solutions.\n- Advise customers\n- Improve products"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 21


def test_bossard_rejects_unconfirmed_zug_facet() -> None:
    parser = BossardSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(1)],
                    facet_id="different-location",
                    facet_name="Berlin",
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="confirm the requested Zug facet"):
        parser.search(LinkedInSearchRequest())


def test_bossard_removes_foreign_record_leaked_by_location_facet() -> None:
    records = [listing_record(1), listing_record(2)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload(records))
        index = int(request.url.path.split("Application-Engineer-")[1].split("_")[0])
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

    result = BossardSwitzerlandJobsParser(
        base_url="https://bossard.example.test/BossardJobs",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["Senior Application Engineer 1 | Bossard AG"]
    assert "from 2 Workday Zug facet records" in result.message


def test_bossard_preserves_verified_facet_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload([listing_record(7)]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        BossardSwitzerlandJobsParser(
            base_url="https://bossard.example.test/BossardJobs",
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Application Engineer 7 | Bossard AG"
    assert job.company == "Bossard AG"
    assert job.location == "Zug"
    assert job.url.endswith("/Application-Engineer-7_JR00007")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_bossard_rejects_invalid_truncated_or_oversized_catalog() -> None:
    invalid = BossardSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    truncated = BossardSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([listing_record(1)], total=2),
            )
        )
    )
    oversized = BossardSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(20)],
                    total=21,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_bossard_wraps_listing_request_failures() -> None:
    parser = BossardSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_bossard_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bossard_switzerland"]
    assert isinstance(parser, BossardSwitzerlandJobsParser)
    assert parser.base_url == settings.bossard_switzerland_jobs_base_url
    assert parser.max_pages == settings.bossard_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.bossard_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bossard Switzerland", "filters": {}},
            "sources": ["bossard_switzerland", "bossard_switzerland"],
        }
    )
    assert request.sources == ["bossard_switzerland"]


def test_bossard_jobs_render_as_direct_company_imports() -> None:
    parser = BossardSwitzerlandJobsParser()
    record = listing_record(1)
    record["detail"] = detail_payload(1)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="bossard_switzerland-jr00001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bossard Switzerland import"
    assert stored["id"] == "bossard_switzerland-jr00001"
