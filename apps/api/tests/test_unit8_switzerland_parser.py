from __future__ import annotations

from datetime import UTC, datetime
from textwrap import dedent

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.unit8_switzerland import (
    Unit8SwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def catalog_row(
    *,
    shortcode: str,
    title: str,
    country: str,
    country_code: str,
    city: str,
    region: str,
) -> dict[str, object]:
    return {
        "title": title,
        "shortcode": shortcode,
        "code": "",
        "employment_type": "Full-time",
        "telecommuting": False,
        "department": "Engineering",
        "url": f"https://apply.workable.com/j/{shortcode}",
        "shortlink": f"https://apply.workable.com/j/{shortcode}",
        "application_url": f"https://apply.workable.com/j/{shortcode}/apply",
        "published_on": "2026-07-24",
        "created_at": "2026-07-24",
        "country": country,
        "city": city,
        "state": region,
        "education": "Unspecified",
        "experience": "Mid-Senior level",
        "function": "Engineering",
        "industry": "Information Technology and Services",
        "locations": [
            {
                "country": country,
                "countryCode": country_code,
                "city": city,
                "region": region,
                "hidden": False,
            }
        ],
    }


def detail_markdown(
    *,
    shortcode: str,
    title: str,
    location: str = "Zürich, Switzerland (Hybrid)",
) -> str:
    return dedent(f"""
    # {title}

    > Unit8 SA · {location} · Full-time · Posted 2026-07-24

    **Workplace:** hybrid

    ## Description

    ### **Who We Are**

    Unit8 builds Swiss AI solutions.

    ## Requirements

    ### **What You’ll Do**

    - Design data platforms
    - Advise clients

    ## Apply

    [Apply at Unit8 SA](https://apply.workable.com/unit8/j/{shortcode}/apply)
    """)


def swiss_catalog() -> list[dict[str, object]]:
    return [
        catalog_row(
            shortcode="DA88B40606",
            title="Palantir Foundry Engineer (Switzerland)",
            country="Switzerland",
            country_code="CH",
            city="Zürich",
            region="Zurich",
        ),
        catalog_row(
            shortcode="DA88B40606",
            title="Palantir Foundry Engineer (Switzerland)",
            country="Switzerland",
            country_code="CH",
            city="Lausanne",
            region="Vaud",
        ),
        catalog_row(
            shortcode="14E470F5E8",
            title="Senior Data & AI Consultant (Switzerland)",
            country="Switzerland",
            country_code="CH",
            city="Zürich",
            region="Zurich",
        ),
        catalog_row(
            shortcode="E7A5A08F78",
            title="Palantir Foundry Engineer (Germany)",
            country="Germany",
            country_code="DE",
            city="Munich",
            region="Bavaria",
        ),
    ]


def test_unit8_scans_only_swiss_jobs_and_merges_swiss_locations() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/widget/accounts/unit8":
            return httpx.Response(
                200,
                json={
                    "name": "Unit8 SA",
                    "description": "Swiss data and AI consultancy",
                    "jobs": swiss_catalog(),
                },
            )
        if request.url.path == "/unit8/jobs/view/DA88B40606.md":
            return httpx.Response(
                200,
                text=detail_markdown(
                    shortcode="DA88B40606",
                    title="Palantir Foundry Engineer (Switzerland)",
                ),
            )
        return httpx.Response(
            200,
            text=detail_markdown(
                shortcode="14E470F5E8",
                title="Senior Data & AI Consultant (Switzerland)",
            ),
        )

    parser = Unit8SwitzerlandJobsParser(
        base_url="https://unit8.test/career/",
        api_url="https://apply.workable.com/api/v1/widget/accounts/unit8",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Unit8 Switzerland vacancies from 3 global Workable postings"
    )
    assert len(requests) == 3
    assert len(result.jobs) == 2
    assert {job.raw["id"] for job in result.jobs} == {
        "DA88B40606",
        "14E470F5E8",
    }
    assert all(
        location["countryCode"] == "CH" for job in result.jobs for location in job.raw["locations"]
    )

    first = result.jobs[0]
    assert first.source == "unit8_switzerland"
    assert first.title == "Palantir Foundry Engineer (Switzerland)"
    assert first.company == "Unit8 SA"
    assert first.location == ("Zürich, Zurich, Switzerland; Lausanne, Vaud, Switzerland")
    assert first.url == "https://apply.workable.com/unit8/j/DA88B40606/"
    assert first.apply_url == "https://apply.workable.com/j/DA88B40606/apply"
    assert first.posted_at == "2026-07-24"
    assert first.employment_type == "Full-time"
    assert first.seniority == "Mid-Senior level"
    assert first.description == (
        "Description\n\nWho We Are\n\nUnit8 builds Swiss AI solutions.\n\n"
        "Requirements\n\nWhat You’ll Do\n- Design data platforms\n- Advise clients"
    )
    assert first.raw["catalog_records"] == 2
    assert first.raw["total_available"] == 3
    assert first.raw["swiss_total_available"] == 2
    assert first.raw["detail"]["id"] == "DA88B40606"


def test_unit8_preserves_swiss_listing_when_detail_fails() -> None:
    row = swiss_catalog()[2]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/widget/accounts/unit8":
            return httpx.Response(200, json={"jobs": [row]})
        return httpx.Response(503)

    job = (
        Unit8SwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Data & AI Consultant (Switzerland)"
    assert job.location == "Zürich, Zurich, Switzerland"
    assert job.url == "https://apply.workable.com/j/14E470F5E8"
    assert job.apply_url == "https://apply.workable.com/j/14E470F5E8/apply"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_unit8_rejects_non_swiss_detail_location() -> None:
    row = swiss_catalog()[2]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/widget/accounts/unit8":
            return httpx.Response(200, json={"jobs": [row]})
        return httpx.Response(
            200,
            text=detail_markdown(
                shortcode="14E470F5E8",
                title="Senior Data & AI Consultant (Switzerland)",
                location="Munich, Germany (Hybrid)",
            ),
        )

    job = (
        Unit8SwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Zürich, Zurich, Switzerland"
    assert "incomplete vacancy" in str(job.raw["detail_error"])


@pytest.mark.parametrize("payload", [{"offers": []}, {"jobs": [{}]}])
def test_unit8_rejects_invalid_catalog(payload: object) -> None:
    parser = Unit8SwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workable response"):
        parser.search(LinkedInSearchRequest())


def test_unit8_enforces_global_catalog_limit() -> None:
    parser = Unit8SwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": swiss_catalog()})
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_unit8_wraps_catalog_request_failures() -> None:
    parser = Unit8SwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_unit8_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["unit8_switzerland"]
    assert isinstance(parser, Unit8SwitzerlandJobsParser)
    assert parser.base_url == settings.unit8_switzerland_jobs_base_url
    assert parser.api_url == settings.unit8_switzerland_jobs_api_url
    assert parser.max_jobs == settings.unit8_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.unit8_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Unit8 Switzerland", "filters": {}},
            "sources": ["unit8_switzerland", "unit8_switzerland"],
        }
    )
    assert request.sources == ["unit8_switzerland"]


def test_unit8_jobs_render_as_direct_company_imports() -> None:
    parsed = Unit8SwitzerlandJobsParser().normalize_job(
        {
            "id": "14E470F5E8",
            "title": "Senior Data & AI Consultant (Switzerland)",
            "locations": [
                {
                    "country": "Switzerland",
                    "countryCode": "CH",
                    "city": "Zürich",
                    "region": "Zurich",
                }
            ],
            "url": "https://apply.workable.com/j/14E470F5E8",
            "application_url": "https://apply.workable.com/j/14E470F5E8/apply",
        }
    )

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="unit8_switzerland-14E470F5E8",
        added_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "unit8_switzerland-14E470F5E8"
    assert stored["logo"] == "company"
    assert stored["department"] == "Unit8 Switzerland import"
    assert stored["company"] == "Unit8 SA"
