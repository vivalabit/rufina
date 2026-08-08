from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.raiffeisen import RaiffeisenJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "id": str(10_100_000 + index),
        "viewkey": f"view-key-{index}",
        "title": f"Platform Engineer {index}",
        "attributes": {
            "100": ["Raiffeisen"],
            "arbeitsort": ["Zürich und St. Gallen"],
            "beschaeftigungsart": ["Festanstellung"],
            "53": ["80-100%"],
            "fachbereich": ["Informatik"],
        },
        "szas": {
            "sza_title": f"Senior Platform Engineer {index}",
            "sza_location.city": "Zürich",
            "sza_location.2.city": "St. Gallen",
            "sza_employment_type": "Festanstellung",
            "sza_pensum": "80% - 100%",
            "sza_role": "Fachkräfte",
            "sza_introduction": "Build reliable services.<br/>Work together.",
            "sza_tasks": "<ul><li>Automate the platform</li><li>Improve APIs</li></ul>",
            "sza_requirements": "<ul><li>Python &amp; cloud</li></ul>",
            "sza_benefits": "Flexible working",
            "sza_benefits_2": "Learning budget",
            "sza_apply_link": (
                "https://raiffeisen.wd3.myworkdayjobs.com/jobs-raiffeisen/"
                f"job/Zurich/Platform-Engineer-{index}_R{index:07d}/apply"
            ),
        },
        "links": {
            "directlink": (
                "https://jobs.raiffeisen.example.test/offene-stellen/"
                f"platform-engineer-{index}/view-key-{index}"
            )
        },
        "start_date": "2026-08-07T22:00:00Z",
        "end_date": "2026-09-06T21:59:59Z",
        "language": "de",
    }


def test_raiffeisen_parser_fetches_every_page_and_normalizes_rich_records() -> None:
    records = [listing_record(index) for index in range(98)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/jobs")
        assert request.url.params["lang"] == "de"
        assert request.url.params["limit"] == "96"
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json={
                "total": len(records),
                "offset": offset,
                "jobs": records[offset : offset + 96],
                "filtercount": {},
            },
        )

    parser = RaiffeisenJobsParser(
        base_url="https://jobs.raiffeisen.example.test/",
        api_url="https://api.raiffeisen.example.test/public/v1/medium/1950/jobs",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.status == "completed"
    assert result.search_url == "https://jobs.raiffeisen.example.test/"
    assert result.message == "Scanned 98 Raiffeisen vacancies across 2 API pages"
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "raiffeisen"
    assert first.title == "Platform Engineer 0"
    assert first.company == "Raiffeisen"
    assert first.location == "Zürich und St. Gallen"
    assert first.posted_at == "2026-08-07T22:00:00Z"
    assert first.employment_type == "Festanstellung, 80% - 100%"
    assert first.seniority == "Fachkräfte"
    assert first.url.endswith("/platform-engineer-0/view-key-0")
    assert first.apply_url.endswith("/Platform-Engineer-0_R0000000/apply")
    assert first.description == (
        "Introduction\nBuild reliable services.\nWork together.\n\n"
        "Responsibilities\n- Automate the platform\n- Improve APIs\n\n"
        "Requirements\n- Python & cloud\n\n"
        "Benefits\nFlexible working\n\nLearning budget"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 98


def test_raiffeisen_parser_repeats_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(98)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        if offset == 0:
            page_records = records[:96]
        elif requested_offsets.count(96) == 1:
            page_records = [records[95], records[96]]
        else:
            page_records = records[96:]
        return httpx.Response(
            200,
            json={"total": len(records), "offset": offset, "jobs": page_records},
        )

    parser = RaiffeisenJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98
    assert result.message == "Scanned 98 Raiffeisen vacancies across 4 API pages"


def test_raiffeisen_parser_rejects_invalid_jobs_payload() -> None:
    parser = RaiffeisenJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"total": 4, "jobs": {}}))
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_raiffeisen_parser_does_not_silently_truncate_above_page_limit() -> None:
    parser = RaiffeisenJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total": 193,
                    "offset": 0,
                    "jobs": [listing_record(index) for index in range(96)],
                },
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_raiffeisen_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["raiffeisen"]
    assert isinstance(parser, RaiffeisenJobsParser)
    assert parser.api_url == settings.raiffeisen_jobs_api_url
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Raiffeisen", "filters": {}},
            "sources": ["raiffeisen", "raiffeisen"],
        }
    )
    assert request.sources == ["raiffeisen"]


def test_raiffeisen_jobs_render_as_direct_company_imports() -> None:
    parser = RaiffeisenJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="raiffeisen-10100001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Raiffeisen import"
