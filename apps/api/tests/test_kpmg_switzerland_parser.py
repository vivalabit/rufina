from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.kpmg_switzerland import (
    KpmgSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, language: str = "de") -> dict[str, object]:
    return {
        "id": str(10_100_000 + index),
        "hk_id": str(1_000_000 + index),
        "viewkey": f"view-key-{index}",
        "title": f"Technology Consultant {index}",
        "attributes": {
            "30": ["Zürich", "Genf"],
            "50": ["Vollzeit"],
            "70": ["Berufserfahrene"],
            "90": ["Technology"],
        },
        "szas": {
            "sza_title": f"Technology Consultant {index}",
            "sza_apply_link": str(9000 + index),
            "sza_employment_type": "Festanstellung",
            "sza_pensum": "Vollzeit",
            "sza_pensum.min": "80",
            "sza_pensum.max": "100",
            "sza_role": "Mitarbeiter/in",
            "sza_tasks": "<ul><li>Advise clients</li><li>Build solutions</li></ul>",
            "sza_requirements": "<ul><li>Python &amp; cloud</li></ul>",
            "sza_company_profil": "Make the difference with KPMG.",
            "sza_benefits": "<b>Growth</b><br/>Personal development",
            "sza_benefits_2": "Flexible working",
            "sza_contact": "<b>Jane Example</b><br/>Recruiter",
        },
        "links": {
            "directlink": (
                "https://jobs-ch.kpmg.test/offene-stellen/"
                f"technology-consultant-{index}/view-key-{index}"
            )
        },
        "start_date": "2026-08-08T05:39:32Z",
        "end_date": "2026-09-06T21:59:59Z",
        "language": language,
    }


def test_kpmg_switzerland_fetches_complete_catalog_and_normalizes_records() -> None:
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

    parser = KpmgSwitzerlandJobsParser(
        base_url="https://kpmg.test/ch/de/karriere/offene-stellen.html",
        api_url="https://api.kpmg.test/public/v1/medium/1693/jobs",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 98 KPMG Switzerland vacancies from 98 catalog records "
        "across 2 API page requests"
    )
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "kpmg_switzerland"
    assert first.title == "Technology Consultant 0"
    assert first.company == "KPMG AG"
    assert first.location == "Zürich, Genf"
    assert first.url.endswith("/technology-consultant-0/view-key-0")
    assert first.apply_url == (
        "https://recruitingapp-2791.umantis.com/Vacancies/9000/"
        "Application/CheckLogin?srcIDPMS=10100000&"
        "srcTextPMS=%canalname%&lang=ger"
    )
    assert first.posted_at == "2026-08-08T05:39:32Z"
    assert first.employment_type == "Festanstellung, 80–100%"
    assert first.seniority == "Mitarbeiter/in"
    assert first.description == (
        "Responsibilities\n- Advise clients\n- Build solutions\n\n"
        "Requirements\n- Python & cloud\n\n"
        "About KPMG\nMake the difference with KPMG.\n\n"
        "Benefits\nGrowth\nPersonal development\n\nFlexible working\n\n"
        "Contact\nJane Example\nRecruiter"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 98


def test_kpmg_switzerland_retries_shifted_pages_until_all_ids_are_seen() -> None:
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

    parser = KpmgSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98
    assert result.message.endswith("across 4 API page requests")


def test_kpmg_switzerland_builds_language_specific_apply_urls() -> None:
    parser = KpmgSwitzerlandJobsParser()

    english = parser.normalize_job(listing_record(1, language="en"))
    french = parser.normalize_job(listing_record(2, language="fr"))

    assert english.apply_url and english.apply_url.endswith("&lang=eng")
    assert french.apply_url and french.apply_url.endswith("&lang=fre")


def test_kpmg_switzerland_rejects_invalid_jobs_payload() -> None:
    parser = KpmgSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 4, "jobs": {}})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_kpmg_switzerland_enforces_catalog_page_limit() -> None:
    parser = KpmgSwitzerlandJobsParser(
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


def test_kpmg_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["kpmg_switzerland"]
    assert isinstance(parser, KpmgSwitzerlandJobsParser)
    assert parser.base_url == settings.kpmg_switzerland_jobs_base_url
    assert parser.api_url == settings.kpmg_switzerland_jobs_api_url
    assert parser.max_pages == settings.kpmg_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes == settings.kpmg_switzerland_jobs_max_catalog_passes
    )
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "KPMG Switzerland", "filters": {}},
            "sources": ["kpmg_switzerland", "kpmg_switzerland"],
        }
    )
    assert request.sources == ["kpmg_switzerland"]


def test_kpmg_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = KpmgSwitzerlandJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="kpmg_switzerland-10100001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "KPMG Switzerland import"
    assert stored["id"] == "kpmg_switzerland-10100001"
