from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.axpo_switzerland import (
    AxpoSwitzerlandJobsParser,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def feed_item(
    job_id: int,
    *,
    title: str | None = None,
    company: str = "Axpo Group",
    countries: tuple[str, ...] = ("CH",),
    locations: tuple[str, ...] = ("Baden",),
) -> dict[str, Any]:
    job_title = title or f"Energy Engineer {job_id}"
    return {
        "id": f"feed-{job_id}",
        "title": job_title,
        "url": f"https://careers.axpo.test/jobs/{job_id}-energy-engineer",
        "date_published": "2026-08-10T07:44:37+02:00",
        "content_html": (
            "<p>Build reliable energy systems.</p>"
            "<h3>Responsibilities</h3>"
            "<ul><li>Ship safely.</li></ul>"
        ),
        "_jobposting": {
            "@context": "http://schema.org/",
            "@type": "JobPosting",
            "title": job_title,
            "description": "<p>Build reliable energy systems.</p>",
            "identifier": {
                "@type": "PropertyValue",
                "name": company,
                "value": job_id,
            },
            "datePosted": "2026-08-10T07:44:37+02:00",
            "employmentType": "FULL_TIME",
            "hiringOrganization": {
                "@type": "Organization",
                "name": company,
            },
            "jobLocation": [
                {
                    "@type": "Place",
                    "address": {
                        "@type": "PostalAddress",
                        "addressLocality": location,
                        "addressCountry": country,
                    },
                }
                for location, country in zip(locations, countries, strict=True)
            ],
        },
    }


def feed_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Axpo Group",
        "home_page_url": "https://careers.axpo.test/jobs",
        "feed_url": "https://careers.axpo.test/jobs.json",
        "items": items,
    }


def test_axpo_scans_complete_swiss_json_feed_catalog() -> None:
    requests: list[httpx.Request] = []
    first_page = [feed_item(8_100_000 + index) for index in range(20)]
    first_page[0] = feed_item(
        8_100_000,
        title="NOC Engineer Operations Control Center (w/m/d)",
        company="Axpo Systems AG",
        countries=("CH", "CH", "CH"),
        locations=("Lupfig", "Baden", "Lupfig"),
    )
    second_page = [feed_item(8_100_020), feed_item(8_100_021)]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=feed_payload(first_page if page == 1 else second_page),
        )

    parser = AxpoSwitzerlandJobsParser(
        base_url=("https://careers.axpo.test/jobs?split_view=true&country=Switzerland"),
        feed_url="https://careers.axpo.test/jobs.json",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 22 strictly Swiss Axpo vacancies from 22 country-filtered "
        "Teamtailor postings across 2 JSON Feed pages"
    )
    assert len(requests) == 2
    assert [request.url.params["page"] for request in requests] == ["1", "2"]
    assert all(request.url.params["country"] == "Switzerland" for request in requests)
    assert len(result.jobs) == 22
    first = result.jobs[0]
    assert first.source == "axpo_switzerland"
    assert first.title == "NOC Engineer Operations Control Center (w/m/d)"
    assert first.company == "Axpo Systems AG"
    assert first.location == "Lupfig, Baden"
    assert first.url == "https://careers.axpo.test/jobs/8100000-energy-engineer"
    assert first.apply_url == f"{first.url}/applications/new"
    assert first.posted_at == "2026-08-10T07:44:37+02:00"
    assert first.employment_type == "Full Time"
    assert first.description == ("Build reliable energy systems.\nResponsibilities\nShip safely.")
    assert first.raw["id"] == "8100000"
    assert first.raw["page_number"] == 1
    assert first.raw["schema"]["jobLocation"][0]["address"]["addressCountry"] == "CH"


def test_axpo_rejects_non_swiss_vacancy_in_filtered_feed() -> None:
    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=feed_payload(
                    [
                        feed_item(
                            8_100_001,
                            countries=("CH", "DE"),
                            locations=("Baden", "Berlin"),
                        )
                    ]
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="not exclusively located"):
        parser.search(LinkedInSearchRequest())


def test_axpo_skips_vacancy_without_verifiable_job_location() -> None:
    unlocated = feed_item(8_100_002)
    unlocated["_jobposting"]["jobLocation"] = None
    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=feed_payload([feed_item(8_100_001), unlocated]),
            )
        ),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].raw["id"] == "8100001"
    assert result.message == (
        "Scanned 1 strictly Swiss Axpo vacancies from 2 country-filtered "
        "Teamtailor postings across 1 JSON Feed pages"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": "https://jsonfeed.org/version/1.1", "items": {}},
        feed_payload([{"id": "feed-1"}]),
    ],
)
def test_axpo_rejects_invalid_json_feed_contract(payload: object) -> None:
    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(DirectCompanyRequestError):
        parser.search(LinkedInSearchRequest())


def test_axpo_rejects_duplicate_vacancies_across_pages() -> None:
    first_page = [feed_item(8_200_000 + index) for index in range(20)]

    def handler(request: httpx.Request) -> httpx.Response:
        items = first_page if request.url.params["page"] == "1" else [first_page[0]]
        return httpx.Response(200, json=feed_payload(items))

    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_axpo_rejects_catalog_truncated_by_page_limit() -> None:
    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=feed_payload([feed_item(8_300_000 + index) for index in range(20)]),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1 pages"):
        parser.search(LinkedInSearchRequest())


def test_axpo_enforces_swiss_catalog_size_limit() -> None:
    parser = AxpoSwitzerlandJobsParser(
        feed_url="https://careers.axpo.test/jobs.json",
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=feed_payload([feed_item(8_400_001), feed_item(8_400_002)]),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_axpo_wraps_feed_request_failures() -> None:
    parser = AxpoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_axpo_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["axpo_switzerland"]
    assert isinstance(parser, AxpoSwitzerlandJobsParser)
    assert parser.base_url == settings.axpo_switzerland_jobs_base_url
    assert parser.feed_url == settings.axpo_switzerland_jobs_feed_url
    assert parser.max_pages == settings.axpo_switzerland_jobs_max_pages
    assert parser.max_jobs == settings.axpo_switzerland_jobs_max_jobs
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Axpo Switzerland", "filters": {}},
            "sources": ["axpo_switzerland", "axpo_switzerland"],
        }
    )
    assert request.sources == ["axpo_switzerland"]


def test_axpo_jobs_render_as_direct_company_imports() -> None:
    parser = AxpoSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "8196100",
            "title": "Mitarbeiter/in Betriebsdienst (Schicht) (w/m/d)",
            "company": "Axpo Group",
            "location": "Stalden",
            "url": (
                "https://careers.axpo.com/jobs/8196100-mitarbeiter-in-betriebsdienst-schicht-w-m-d"
            ),
            "posted_at": "2026-08-10T07:44:37+02:00",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="axpo_switzerland-8196100",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Axpo Switzerland import"
    assert stored["id"] == "axpo_switzerland-8196100"
