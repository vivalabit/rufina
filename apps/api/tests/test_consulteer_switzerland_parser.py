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
from app.services.parsers.companies.consulteer_switzerland import (
    ConsulteerSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.consulteer.com/careers"
API_URL = "https://consulteer1.recruitee.com/api/offers/"


def location(
    city: str,
    *,
    country_code: str = "CH",
    state: str | None = "Bern",
    country: str | None = None,
) -> dict[str, Any]:
    return {
        "id": abs(hash((city, country_code, state))) % 1_000_000,
        "name": city,
        "city": city,
        "state": state,
        "country": country
        or ("Switzerland" if country_code == "CH" else "Germany"),
        "country_code": country_code,
    }


def offer(
    job_id: int,
    slug: str,
    *,
    title: str,
    locations: list[dict[str, Any]],
    guid: str | None = None,
    company_name: str = "Consulteer",
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
        "careers_url": public_url
        or f"https://consulteer1.recruitee.com/o/{slug}",
        "careers_apply_url": apply_url
        or f"https://consulteer1.recruitee.com/o/{slug}/c/new",
        "published_at": "2026-08-13 09:31:30 UTC",
        "employment_type_code": "fulltime_permanent",
        "experience_code": "mid_level",
        "description": (
            "<p>Design resilient enterprise solutions.</p>"
            "<h2>Your Role &amp; Responsibilities</h2>"
            "<ul><li><p>Define scalable architectures.</p></li></ul>"
        ),
        "requirements": (
            "<h2>Required Expertise</h2>"
            "<ul><li><p>Strong Java and Spring experience.</p></li></ul>"
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
            1780463,
            "solutions-architect-1",
            title="Solutions Architect",
            locations=[location("Bern")],
        ),
        offer(
            1849303,
            "test-manager-1",
            title="Test Manager",
            locations=[
                location("Bern", state="Berne"),
                location("Zurich", state="Zürich"),
            ],
        ),
        offer(
            2667820,
            "sales-manager-medtech-healthcare-mwd",
            title="Sales Manager MedTech & Healthcare (m/w/d)",
            locations=[location("München", country_code="DE", state="Bayern")],
        ),
    ]


def parser_for(
    offers: list[dict[str, Any]],
    *,
    status_code: int = 200,
    **kwargs: Any,
) -> ConsulteerSwitzerlandJobsParser:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, request=request)
        return httpx.Response(200, json={"offers": offers}, request=request)

    return ConsulteerSwitzerlandJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_consulteer_collects_complete_catalog_and_keeps_swiss_jobs() -> None:
    result = parser_for(catalog_fixture()).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Consulteer Swiss vacancies from 3 global Recruitee records"
    )
    assert [job.title for job in result.jobs] == [
        "Solutions Architect",
        "Test Manager",
    ]

    job = result.jobs[0]
    assert job.source == "consulteer_switzerland"
    assert job.company == "Consulteer"
    assert job.location == "Bern, Bern, Switzerland"
    assert job.url == "https://www.consulteer.com/careers/solutions-architect-1"
    assert job.apply_url == (
        "https://consulteer1.recruitee.com/o/solutions-architect-1/c/new"
    )
    assert job.posted_at == "2026-08-13"
    assert job.employment_type == "Full-time, permanent"
    assert job.seniority == "Mid level"
    assert job.description == (
        "Design resilient enterprise solutions.\n"
        "Your Role & Responsibilities\n"
        "- Define scalable architectures.\n\n"
        "Required Expertise\n"
        "- Strong Java and Spring experience."
    )
    assert job.raw["id"] == 1780463
    assert job.raw["recruitee_url"] == (
        "https://consulteer1.recruitee.com/o/solutions-architect-1"
    )


def test_consulteer_preserves_all_swiss_locations() -> None:
    job = parser_for(catalog_fixture()).search(LinkedInSearchRequest()).jobs[1]

    assert job.location == (
        "Bern, Berne, Switzerland; Zurich, Zürich, Switzerland"
    )
    assert [item["country_code"] for item in job.raw["swiss_locations"]] == [
        "CH",
        "CH",
    ]


def test_consulteer_filters_mixed_location_offer_to_swiss_locations() -> None:
    mixed_offer = offer(
        2000001,
        "platform-engineer",
        title="Platform Engineer",
        locations=[
            location("Zurich", state="Zürich"),
            location("Munich", country_code="DE", state="Bayern"),
        ],
    )

    job = parser_for([mixed_offer]).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Zurich, Zürich, Switzerland"
    assert len(job.raw["locations"]) == 2
    assert len(job.raw["swiss_locations"]) == 1


def test_consulteer_rejects_identity_and_catalog_inconsistencies() -> None:
    wrong_company = catalog_fixture()
    wrong_company[0]["company_name"] = "Another Company"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(wrong_company).search(LinkedInSearchRequest())

    wrong_url = catalog_fixture()
    wrong_url[0]["careers_apply_url"] = (
        "https://consulteer1.recruitee.com/o/another-role/c/new"
    )
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(wrong_url).search(LinkedInSearchRequest())

    duplicate = catalog_fixture()
    duplicate[1]["guid"] = duplicate[0]["guid"]
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy"):
        parser_for(duplicate).search(LinkedInSearchRequest())


def test_consulteer_rejects_invalid_locations_and_broken_catalogs() -> None:
    invalid_location = catalog_fixture()
    invalid_location[0]["locations"][0]["country_code"] = "Switzerland"
    with pytest.raises(DirectCompanyRequestError, match="incomplete location"):
        parser_for(invalid_location).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="catalog is empty"):
        parser_for([]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parser_for(catalog_fixture(), max_jobs=2).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser_for([], status_code=503).search(LinkedInSearchRequest())


def test_consulteer_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["consulteer_switzerland"]
    assert isinstance(parser, ConsulteerSwitzerlandJobsParser)
    assert parser.base_url == settings.consulteer_switzerland_jobs_base_url
    assert parser.api_url == settings.consulteer_switzerland_jobs_api_url
    assert parser.max_jobs == settings.consulteer_switzerland_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Consulteer", "filters": {}},
            "sources": ["consulteer_switzerland", "consulteer_switzerland"],
        }
    )
    assert request.sources == ["consulteer_switzerland"]


def test_consulteer_jobs_render_as_direct_company_imports() -> None:
    record = catalog_fixture()[0]
    record["swiss_locations"] = record["locations"]
    job = ConsulteerSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="consulteer_switzerland-1780463",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Consulteer Switzerland import"
    assert stored["id"] == "consulteer_switzerland-1780463"
