from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.schneider_electric_switzerland import (
    SchneiderElectricSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(
    job_id: int,
    *,
    primary_country: str = "Switzerland",
    primary_country_code: str = "CH",
    additional_locations: list[dict[str, Any]] | None = None,
    req_id: str | None = None,
    organization: str = "Schneider Electric",
) -> dict[str, Any]:
    language = "de-de"
    data: dict[str, Any] = {
        "slug": str(job_id),
        "req_id": req_id or str(job_id),
        "language": language,
        "languages": [language],
        "title": f"Automation Engineer {job_id} (m/w/d) 80-100%",
        "description": (
            "Shape sustainable automation with Schneider Electric.\n"
            "Für diese Position in Switzerland liegt das Jahreszielgehalt "
            "bei min. CHF 82'800 pro Jahr."
        ),
        "location_name": (
            "Switzerland-Zurich-Horgen" if primary_country_code == "CH" else primary_country
        ),
        "city": "Zurich-Horgen" if primary_country_code == "CH" else None,
        "state": "Zurich" if primary_country_code == "CH" else None,
        "country": primary_country,
        "country_code": primary_country_code,
        "additional_locations": additional_locations or [],
        "categories": [{"name": "IT Services and Solutions"}],
        "tags7": ["Hybrid"],
        "employment_type": "FULL_TIME",
        "hiring_organization": organization,
        "posted_date": "August 14, 2026",
        "apply_url": f"https://grcareers-se.icims.com/jobs/{job_id}/login",
        "meta_data": {
            "canonical_url": f"https://careers.se.com/jobs/{job_id}?lang={language}",
            "icims": {"primary_posted_site_object": {"datePosted": "2026-08-14T09:30:00+0000"}},
        },
    }
    return {"data": data}


def payload(
    records: list[dict[str, Any]],
    *,
    total: int,
    page_size: int = 10,
    country_count: int | None = None,
) -> dict[str, Any]:
    facets = (
        []
        if total == 0
        else [
            {"term": "Germany", "count": 1},
            {
                "term": "Switzerland",
                "count": total if country_count is None else country_count,
            },
        ]
    )
    return {
        "jobs": records,
        "totalCount": total,
        "count": len(records),
        "filter": {
            "displayLimit": page_size,
            "facetList": {"country": facets},
        },
    }


def parser_with(
    fetch_page: object,
    **kwargs: object,
) -> SchneiderElectricSwitzerlandJobsParser:
    return SchneiderElectricSwitzerlandJobsParser(
        fetch_page=fetch_page,  # type: ignore[arg-type]
        **kwargs,
    )


def test_schneider_scans_every_country_page_and_normalizes_jobs() -> None:
    records = [vacancy(index) for index in range(101, 113)]
    requested_pages: list[int] = []

    def fetch_page(url: str) -> dict[str, Any]:
        parts = urlsplit(url)
        assert parts.path == "/api/jobs"
        params = parse_qs(parts.query)
        assert params["country"] == ["Switzerland"]
        assert params["lang"] == ["de-DE"]
        assert params["internal"] == ["false"]
        page_number = int(params["page"][0])
        requested_pages.append(page_number)
        start = (page_number - 1) * 10
        return payload(records[start : start + 10], total=len(records))

    result = parser_with(fetch_page, page_workers=2).search(LinkedInSearchRequest(results_limit=1))

    assert sorted(requested_pages) == [1, 2]
    assert len(result.jobs) == 12
    assert result.message == (
        "Scanned 12 verified Schneider Electric Switzerland vacancies from 12 "
        "Jibe country records across 2 page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "schneider_electric_switzerland"
    assert first.company == "Schneider Electric"
    assert first.title == "Automation Engineer 101 (m/w/d) 80-100%"
    assert first.location == "Zurich-Horgen, Zurich, Switzerland"
    assert first.url == "https://careers.se.com/jobs/101?lang=de-de"
    assert first.apply_url == "https://grcareers-se.icims.com/jobs/101/login"
    assert first.posted_at == "2026-08-14"
    assert first.employment_type == "Full Time"
    assert first.salary == "From CHF 82,800 per year"
    assert first.salary_min == 82_800
    assert first.salary_currency == "CHF"
    assert first.salary_unit == "year"
    assert first.description and "Shape sustainable automation" in first.description
    assert first.raw["category"] == "IT Services and Solutions"
    assert first.raw["work_model"] == "Hybrid"
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 12


def test_schneider_keeps_swiss_additional_location_for_dach_vacancy() -> None:
    record = vacancy(
        114396,
        primary_country="Germany",
        primary_country_code="DE",
        additional_locations=[
            {
                "location_name": "Austria",
                "country": "Austria",
                "country_code": "AT",
            },
            {
                "location_name": "Switzerland",
                "country": "Switzerland",
                "country_code": "CH",
            },
        ],
    )
    parser = parser_with(lambda _: payload([record], total=1))

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Switzerland"
    assert "Germany" not in job.location
    assert "Austria" not in job.location


def test_schneider_retries_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def fetch_page(url: str) -> dict[str, Any]:
        nonlocal first_page_calls
        page_number = int(parse_qs(urlsplit(url).query)["page"][0])
        if page_number == 1:
            first_page_calls += 1
            return payload([vacancy(101), vacancy(102)], total=3, page_size=2)
        job_id = 102 if first_page_calls == 1 else 103
        return payload([vacancy(job_id)], total=3, page_size=2)

    result = parser_with(fetch_page, page_workers=1).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests in 2 catalog pass(es)")


def test_schneider_rejects_vacancy_without_a_swiss_location() -> None:
    parser = parser_with(
        lambda _: payload(
            [
                vacancy(
                    101,
                    primary_country="Germany",
                    primary_country_code="DE",
                )
            ],
            total=1,
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_schneider_rejects_mismatched_vacancy_identity() -> None:
    parser = parser_with(lambda _: payload([vacancy(101, req_id="999")], total=1))

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_schneider_rejects_an_unverified_country_facet() -> None:
    parser = parser_with(lambda _: payload([vacancy(101)], total=1, country_count=2))

    with pytest.raises(DirectCompanyRequestError, match="declared total"):
        parser.search(LinkedInSearchRequest())


def test_schneider_accepts_the_verified_empty_catalog() -> None:
    parser = parser_with(lambda _: payload([], total=0))

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 verified Schneider Electric Switzerland vacancies from 0 "
        "Jibe country records across 1 page requests in 1 catalog pass(es)"
    )


def test_schneider_enforces_catalog_page_limit() -> None:
    parser = parser_with(
        lambda _: payload([vacancy(101), vacancy(102)], total=3, page_size=2),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_schneider_rejects_truncated_catalog_after_retry_budget() -> None:
    parser = parser_with(
        lambda _: payload([vacancy(101)], total=2, page_size=10),
        max_catalog_passes=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        parser.search(LinkedInSearchRequest())


def test_schneider_rejects_base_url_without_switzerland_scope() -> None:
    parser = parser_with(
        lambda _: payload([], total=0),
        base_url="https://careers.se.com/jobs?lang=de-DE&country=Germany&page=1",
    )

    with pytest.raises(DirectCompanyRequestError, match="lost its Switzerland"):
        parser.search(LinkedInSearchRequest())


def test_schneider_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["schneider_electric_switzerland"]
    assert isinstance(parser, SchneiderElectricSwitzerlandJobsParser)
    assert parser.base_url == settings.schneider_electric_switzerland_jobs_base_url
    assert parser.max_pages == settings.schneider_electric_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes == settings.schneider_electric_switzerland_jobs_max_catalog_passes
    )
    assert parser.page_workers == settings.schneider_electric_switzerland_jobs_page_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Schneider Electric Switzerland", "filters": {}},
            "sources": [
                "schneider_electric_switzerland",
                "schneider_electric_switzerland",
            ],
        }
    )
    assert request.sources == ["schneider_electric_switzerland"]


def test_schneider_jobs_render_as_direct_company_imports() -> None:
    job = SchneiderElectricSwitzerlandJobsParser().normalize_job(
        {
            "id": "117294",
            "title": "Quality Assurance Engineer",
            "location": "Zurich-Horgen, Zurich, Switzerland",
            "url": "https://careers.se.com/jobs/117294?lang=de-de",
            "apply_url": "https://grcareers-se.icims.com/jobs/117294/login",
            "description": "Quality engineering",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="schneider_electric_switzerland-117294",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Schneider Electric Switzerland import"
    assert stored["id"] == "schneider_electric_switzerland-117294"
