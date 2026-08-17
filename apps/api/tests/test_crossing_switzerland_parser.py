from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.crossing_switzerland import (
    CrossingSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://crossing.recruitee.com/?jobs-c88dea0d%5Bcountry%5D%5B%5D=CH"
API_URL = "https://crossing.recruitee.com/api/offers/"


def location(
    city: str,
    *,
    country_code: str = "CH",
    state: str | None = "Zürich",
) -> dict[str, Any]:
    return {
        "city": city,
        "state": state,
        "country": "Schweiz" if country_code == "CH" else "Deutschland",
        "country_code": country_code,
    }


def offer(
    job_id: int,
    slug: str,
    *,
    title: str,
    locations: list[dict[str, Any]],
    guid: str | None = None,
    company_name: str = "cross-ING AG",
    status: str = "published",
    public_url: str | None = None,
    apply_url: str | None = None,
) -> dict[str, Any]:
    primary = locations[0]
    return {
        "id": job_id,
        "guid": guid or f"guid{job_id}",
        "slug": slug,
        "title": title,
        "company_name": company_name,
        "status": status,
        "careers_url": public_url or f"https://crossing.recruitee.com/o/{slug}",
        "careers_apply_url": apply_url or f"https://crossing.recruitee.com/o/{slug}/c/new",
        "published_at": "2026-06-24 10:24:04 UTC",
        "employment_type_code": "fulltime_permanent",
        "experience_code": "mid_level",
        "description": "<p>cross-ING ist ein Schweizer Ingenieurbüro.</p>",
        "requirements": (
            "<p><strong>Deine Aufgaben</strong></p>"
            "<ul><li>Entwickle zuverlässige Systeme.</li>"
            "<li>Arbeite mit Kunden zusammen.</li></ul>"
        ),
        "highlight": None,
        "locations": locations,
        "country_code": primary["country_code"],
        "country": primary["country"],
        "city": primary["city"],
        "salary": {"min": None, "max": None, "currency": None, "period": None},
    }


def catalog_fixture() -> list[dict[str, Any]]:
    return [
        offer(
            2652347,
            "sps-softwareentwickler",
            title="SPS-Softwareentwickler",
            locations=[location("Bern", state="Bern")],
        ),
        offer(
            2033004,
            "prozessingenieur-in",
            title="Prozessingenieur:in",
            locations=[
                location("Dietlikon"),
                location("Winterthur"),
                location("Welzheim", country_code="DE", state="Baden-Württemberg"),
            ],
        ),
        offer(
            1839497,
            "area-business-manager-de",
            title="Area Business Manager Deutschland",
            locations=[location("Welzheim", country_code="DE", state="Baden-Württemberg")],
        ),
    ]


def parser_for(offers: list[dict[str, Any]], *, status_code: int = 200, **kwargs: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, request=request)
        return httpx.Response(200, json={"offers": offers}, request=request)

    return CrossingSwitzerlandJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_crossing_filters_complete_global_catalog_to_swiss_vacancies() -> None:
    result = parser_for(catalog_fixture()).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 cross-ING Swiss vacancies from 3 global Recruitee records")
    assert len(result.jobs) == 2
    assert [job.title for job in result.jobs] == [
        "SPS-Softwareentwickler",
        "Prozessingenieur:in",
    ]

    job = result.jobs[0]
    assert job.source == "crossing_switzerland"
    assert job.company == "cross-ING AG"
    assert job.location == "Bern, Bern, Schweiz"
    assert job.url == "https://crossing.recruitee.com/o/sps-softwareentwickler"
    assert job.apply_url == ("https://crossing.recruitee.com/o/sps-softwareentwickler/c/new")
    assert job.posted_at == "2026-06-24"
    assert job.employment_type == "Full-time, permanent"
    assert job.seniority == "Mid level"
    assert job.description == (
        "cross-ING ist ein Schweizer Ingenieurbüro.\n\n"
        "Deine Aufgaben\n- Entwickle zuverlässige Systeme.\n"
        "- Arbeite mit Kunden zusammen."
    )


def test_crossing_keeps_only_swiss_locations_for_mixed_location_jobs() -> None:
    job = parser_for(catalog_fixture()).search(LinkedInSearchRequest()).jobs[1]

    assert job.location == ("Dietlikon, Zürich, Schweiz; Winterthur, Zürich, Schweiz")
    assert "Welzheim" not in job.location
    assert [item["country_code"] for item in job.raw["swiss_locations"]] == [
        "CH",
        "CH",
    ]
    assert len(job.raw["locations"]) == 3


def test_crossing_rejects_wrong_company_and_duplicate_identifiers() -> None:
    wrong_company = catalog_fixture()
    wrong_company[0]["company_name"] = "Other AG"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(wrong_company).search(LinkedInSearchRequest())

    duplicate = catalog_fixture()
    duplicate[1]["guid"] = duplicate[0]["guid"]
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy identifiers"):
        parser_for(duplicate).search(LinkedInSearchRequest())


def test_crossing_rejects_invalid_locations_and_offer_urls() -> None:
    invalid_location = catalog_fixture()
    invalid_location[0]["locations"][0]["country"] = "Switzerland"
    invalid_location[0]["country"] = "Switzerland"
    with pytest.raises(DirectCompanyRequestError, match="unknown or incomplete location"):
        parser_for(invalid_location).search(LinkedInSearchRequest())

    invalid_url = catalog_fixture()
    invalid_url[0]["careers_apply_url"] = "https://crossing.recruitee.com/o/another-role/c/new"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(invalid_url).search(LinkedInSearchRequest())


def test_crossing_rejects_empty_or_oversized_catalog_and_wraps_http_errors() -> None:
    with pytest.raises(DirectCompanyRequestError, match="catalog is empty"):
        parser_for([]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parser_for(catalog_fixture(), max_jobs=2).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser_for([], status_code=503).search(LinkedInSearchRequest())


def test_crossing_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["crossing_switzerland"]
    assert isinstance(parser, CrossingSwitzerlandJobsParser)
    assert parser.base_url == settings.crossing_switzerland_jobs_base_url
    assert parser.api_url == settings.crossing_switzerland_jobs_api_url
    assert parser.max_jobs == settings.crossing_switzerland_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "cross-ING", "filters": {}},
            "sources": ["crossing_switzerland", "crossing_switzerland"],
        }
    )
    assert request.sources == ["crossing_switzerland"]


def test_crossing_jobs_render_as_direct_company_imports() -> None:
    record = catalog_fixture()[0]
    record["swiss_locations"] = record["locations"]
    job = CrossingSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="crossing_switzerland-2652347",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "cross-ING Switzerland import"
    assert stored["id"] == "crossing_switzerland-2652347"
