from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.buhler_switzerland import (
    BuhlerSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "id": str(10_140_000 + index),
        "hk_id": str(1_018_000 + index),
        "viewkey": f"view-key-{index}",
        "title": f"Automation Engineer {index}",
        "attributes": {
            "10": ["Forschung & Entwicklung"],
            "20": ["Schweiz"],
            "30": ["Fachkräfte"],
            "40": ["Unbefristet"],
            "50": ["80-100%"],
            "60": ["Hybrid"],
        },
        "szas": {
            "sza_title": f"Automation Engineer {index}",
            "sza_apply_link": (
                "https://jobs.buhler.test/successfactors/DC74_PROD/"
                f"buhlergroup/de/apply?id={3_400 + index}"
            ),
            "sza_employment_type": "Unbefristet",
            "sza_pensum": "80-100%",
            "sza_pensum.min": "80",
            "sza_pensum.max": "100",
            "sza_workplace.city": "Uzwil",
            "sza_workplace.country": "Schweiz",
            "sza_introduction": "Gestalten Sie nachhaltige Lösungen.",
            "sza_tasks": ("<ul><li>Build controls</li><li>Improve plants</li></ul>"),
            "sza_requirements": "<ul><li>PLC &amp; cloud</li></ul>",
            "sza_company_profil": "Bühler creates innovations for a better world.",
            "sza_benefits": "<b>Flexible work</b><br/>Personal development",
        },
        "links": {
            "directlink": (
                "https://jobs.buhler.test/offene-stellen/"
                f"automation-engineer-{index}/view-key-{index}"
            )
        },
        "start_date": "2026-08-08T05:39:32Z",
        "end_date": "2027-02-03T22:59:59Z",
        "language": "de",
    }


def payload(
    records: list[dict[str, object]],
    *,
    total: int,
    offset: int,
) -> dict[str, object]:
    return {"total": total, "offset": offset, "jobs": records}


def test_buhler_switzerland_fetches_complete_filtered_catalog() -> None:
    records = [listing_record(index) for index in range(98)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/jobs")
        assert request.url.params["lang"] == "de"
        assert request.url.params["limit"] == "96"
        assert request.url.params["f"] == "20:1708896"
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=payload(
                records[offset : offset + 96],
                total=len(records),
                offset=offset,
            ),
        )

    parser = BuhlerSwitzerlandJobsParser(
        base_url="https://jobs.buhler.test/?lang=de",
        api_url="https://api.buhler.test/public/v1/medium/1008005/jobs",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 98 Bühler Schweiz vacancies from 98 catalog records across 2 API page requests"
    )
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "buhler_switzerland"
    assert first.title == "Automation Engineer 0"
    assert first.company == "Bühler AG"
    assert first.location == "Uzwil, Schweiz"
    assert first.url.endswith("/automation-engineer-0/view-key-0")
    assert first.apply_url and first.apply_url.endswith("/de/apply?id=3400")
    assert first.posted_at == "2026-08-08T05:39:32Z"
    assert first.employment_type == "Unbefristet, 80-100%, Hybrid"
    assert first.seniority == "Fachkräfte"
    assert first.description == (
        "Einleitung\nGestalten Sie nachhaltige Lösungen.\n\n"
        "Aufgaben\n- Build controls\n- Improve plants\n\n"
        "Anforderungen\n- PLC & cloud\n\n"
        "Über Bühler\nBühler creates innovations for a better world.\n\n"
        "Benefits\nFlexible work\nPersonal development"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 98


def test_buhler_switzerland_retries_shifted_pages_until_all_ids_are_seen() -> None:
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
            json=payload(page_records, total=len(records), offset=offset),
        )

    parser = BuhlerSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98
    assert result.message.endswith("across 4 API page requests")


def test_buhler_switzerland_rejects_invalid_or_non_swiss_payload() -> None:
    invalid_jobs = BuhlerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"total": 1, "offset": 0, "jobs": {}},
            )
        )
    )
    non_swiss_record = listing_record(1)
    non_swiss_record["attributes"] = {"20": ["Deutschland"]}
    non_swiss = BuhlerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=payload([non_swiss_record], total=1, offset=0),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        invalid_jobs.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        non_swiss.search(LinkedInSearchRequest())


def test_buhler_switzerland_enforces_catalog_page_limit() -> None:
    parser = BuhlerSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=payload(
                    [listing_record(index) for index in range(96)],
                    total=97,
                    offset=0,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_buhler_switzerland_wraps_listing_request_failures() -> None:
    parser = BuhlerSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_buhler_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["buhler_switzerland"]
    assert isinstance(parser, BuhlerSwitzerlandJobsParser)
    assert parser.base_url == settings.buhler_switzerland_jobs_base_url
    assert parser.api_url == settings.buhler_switzerland_jobs_api_url
    assert parser.max_pages == settings.buhler_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.buhler_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bühler Schweiz", "filters": {}},
            "sources": ["buhler_switzerland", "buhler_switzerland"],
        }
    )
    assert request.sources == ["buhler_switzerland"]


def test_buhler_switzerland_jobs_render_as_direct_company_imports() -> None:
    job = BuhlerSwitzerlandJobsParser().normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="buhler_switzerland-10140001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bühler Schweiz import"
    assert stored["id"] == "buhler_switzerland-10140001"
