from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.emmi import EmmiJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "id": str(10_100_000 + index),
        "hk_id": str(1_000_000 + index),
        "viewkey": f"view-key-{index}",
        "title": f"Automation Engineer {index}",
        "attributes": {
            "10": ["Technik"],
            "20": ["Festanstellung"],
            "30": ["Teilzeit"],
            "40": ["Zentralschweiz (LU, NW, OW, SZ, UR, ZG)"],
            "50": ["Ja"],
        },
        "szas": {
            "sza_title": f"Automation Engineer {index}",
            "sza_apply_link": (
                "https://atsconnector.prospective.test/successfactors/"
                f"EMEA_ROT/ProdEmmi/de/apply?id={19_000 + index}"
            ),
            "sza_employment_type": "Festanstellung",
            "sza_pensum.min": "80",
            "sza_pensum.max": "100",
            "sza_location.city": "Luzern",
            "sza_role": "Mitarbeiter/in",
            "sza_tasks": "<ul><li>Build controls</li><li>Improve plants</li></ul>",
            "sza_requirements": "<ul><li>PLC &amp; cloud</li></ul>",
            "sza_company_profil": "Emmi makes high-quality dairy products.",
            "sza_benefits": "<b>Flexible work</b><br/>Personal development",
            "sza_application": "We look forward to your application.",
        },
        "links": {
            "directlink": (
                "https://jobs.emmi.test/offene-stellen/"
                f"automation-engineer-{index}/view-key-{index}"
            )
        },
        "start_date": "2026-08-08T05:39:32Z",
        "end_date": "2053-12-21T22:59:59Z",
        "language": "de",
    }


def test_emmi_fetches_complete_catalog_and_normalizes_records() -> None:
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

    parser = EmmiJobsParser(
        base_url="https://group.emmi.test/che/de/offene-stellen",
        api_url="https://api.emmi.test/public/v1/medium/1003228/jobs",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 98 Emmi vacancies from 98 catalog records across 2 API page requests"
    )
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "emmi"
    assert first.title == "Automation Engineer 0"
    assert first.company == "Emmi"
    assert first.location == "Luzern"
    assert first.url.endswith("/automation-engineer-0/view-key-0")
    assert first.apply_url and first.apply_url.endswith("/de/apply?id=19000")
    assert first.posted_at == "2026-08-08T05:39:32Z"
    assert first.employment_type == "Festanstellung, 80–100%"
    assert first.seniority == "Mitarbeiter/in"
    assert first.description == (
        "Aufgaben\n- Build controls\n- Improve plants\n\n"
        "Anforderungen\n- PLC & cloud\n\n"
        "Über Emmi\nEmmi makes high-quality dairy products.\n\n"
        "Benefits\nFlexible work\nPersonal development\n\n"
        "Bewerbung\nWe look forward to your application."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 98


def test_emmi_retries_shifted_pages_until_all_ids_are_seen() -> None:
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

    parser = EmmiJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98
    assert result.message.endswith("across 4 API page requests")


def test_emmi_rejects_invalid_or_incomplete_jobs_payload() -> None:
    invalid_jobs = EmmiJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"total": 1, "jobs": {}}))
    )
    incomplete_job = EmmiJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 1, "jobs": [{"id": "101", "title": "Engineer"}]},
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        invalid_jobs.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        incomplete_job.search(LinkedInSearchRequest())


def test_emmi_enforces_catalog_page_limit() -> None:
    parser = EmmiJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "total": 97,
                    "offset": 0,
                    "jobs": [listing_record(index) for index in range(96)],
                },
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_emmi_wraps_listing_request_failures() -> None:
    parser = EmmiJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_emmi_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["emmi"]
    assert isinstance(parser, EmmiJobsParser)
    assert parser.base_url == settings.emmi_jobs_base_url
    assert parser.api_url == settings.emmi_jobs_api_url
    assert parser.max_pages == settings.emmi_jobs_max_pages
    assert parser.max_catalog_passes == settings.emmi_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Emmi", "filters": {}},
            "sources": ["emmi", "emmi"],
        }
    )
    assert request.sources == ["emmi"]


def test_emmi_jobs_render_as_direct_company_imports() -> None:
    job = EmmiJobsParser().normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="emmi-10100001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Emmi import"
    assert stored["id"] == "emmi-10100001"
