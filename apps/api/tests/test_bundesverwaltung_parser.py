from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bundesverwaltung import (
    BundesverwaltungJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "id": str(10_140_000 + index),
        "viewkey": f"view-key-{index}",
        "title": f"Platform Engineer {index}",
        "attributes": {
            "25": ["Berufserfahrene und Berufseinsteiger/innen"],
            "arbeitsort": ["Bern"],
            "verwaltungseinheit_1083352": ["Bundesamt für Informatik BIT"],
            "verwaltungseinheit": ["EFD"],
            "70": ["80"],
            "75": ["100"],
        },
        "szas": {
            "sza_title": f"Senior Platform Engineer {index}",
            "sza_location.city": "Zollikofen",
            "sza_role": "Fachfunktion",
            "sza_pensum.min": "80",
            "sza_pensum.max": "100",
            "sza_tasks": (
                "<ul><li>Automate the platform</li><li>Improve APIs</li></ul>"
            ),
            "sza_requirements": "<ul><li>Python &amp; cloud</li></ul>",
            "sza_company_profil": "Digital services for Switzerland.<br/>Together.",
            "sza_benefits": "<ul><li>Flexible working</li></ul>",
            "sza_contact": "<b>Alex Example</b><br/>Hiring manager",
            "sza_apply_link": (
                "https://career74.sapsf.eu/career?company=bundesamtf&"
                f"career_ns=job_application&career_job_req_id={index}"
            ),
        },
        "links": {
            "directlink": (
                "https://jobs.admin.example.test/offene-stellen/"
                f"platform-engineer-{index}/view-key-{index}"
            )
        },
        "start_date": "2026-08-07T10:59:41Z",
        "end_date": "2026-09-05T21:59:59Z",
        "language": "de",
    }


def test_bundesverwaltung_fetches_every_page_and_normalizes_rich_records() -> None:
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
            },
        )

    parser = BundesverwaltungJobsParser(
        base_url="https://jobs.admin.example.test/?lang=de",
        api_url=(
            "https://api.admin.example.test/public/v1/medium/1000624/jobs"
        ),
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.status == "completed"
    assert result.search_url == "https://jobs.admin.example.test/?lang=de"
    assert result.message == (
        "Scanned 98 Bundesverwaltung vacancies across 2 API pages"
    )
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "bundesverwaltung"
    assert first.title == "Platform Engineer 0"
    assert first.company == "Bundesamt für Informatik BIT"
    assert first.location == "Bern"
    assert first.posted_at == "2026-08-07T10:59:41Z"
    assert first.employment_type == "80–100%"
    assert first.seniority == "Berufserfahrene und Berufseinsteiger/innen"
    assert first.url.endswith("/platform-engineer-0/view-key-0")
    assert first.apply_url.endswith("career_job_req_id=0")
    assert first.description == (
        "Responsibilities\n- Automate the platform\n- Improve APIs\n\n"
        "Requirements\n- Python & cloud\n\n"
        "About the employer\nDigital services for Switzerland.\nTogether.\n\n"
        "Benefits\n- Flexible working\n\n"
        "Contact\nAlex Example\nHiring manager"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 98


def test_bundesverwaltung_repeats_shifted_pages_until_all_ids_are_seen() -> None:
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

    parser = BundesverwaltungJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98


def test_bundesverwaltung_rejects_invalid_jobs_payload() -> None:
    parser = BundesverwaltungJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 4, "jobs": {}})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_bundesverwaltung_does_not_silently_truncate_above_page_limit() -> None:
    parser = BundesverwaltungJobsParser(
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


def test_bundesverwaltung_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bundesverwaltung"]
    assert isinstance(parser, BundesverwaltungJobsParser)
    assert parser.api_url == settings.bundesverwaltung_jobs_api_url
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bundesverwaltung", "filters": {}},
            "sources": ["bundesverwaltung", "bundesverwaltung"],
        }
    )
    assert request.sources == ["bundesverwaltung"]


def test_bundesverwaltung_jobs_render_as_direct_company_imports() -> None:
    parser = BundesverwaltungJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="bundesverwaltung-10140001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bundesverwaltung import"
    assert stored["id"] == "bundesverwaltung-10140001"
