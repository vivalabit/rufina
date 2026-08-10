from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.gritec import GritecJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

PORTALS = (
    ("oqmcwxep", "For those with professional experience and those just getting started"),
    ("04snstaz", "For students (apprenticeships and orientation courses)"),
    ("xfrw5a44", "For university students (placements)"),
    ("te8bsg7b", "For the spontaneous"),
)
SOFTWARE_ID = "63f65b7f-9508-402d-aab7-5ff491cb5f0f"
INITIATIVE_ID = "645349d2-93a9-4360-a272-d79783b803fc"


def career_html(*, portal_host: str = "jobs.dualoo.com") -> str:
    sections = []
    for portal_id, title in PORTALS:
        sections.append(
            f"""
            <div class="node--type-stellenportal">
              <span class="field--name-title">{title}</span>
              <iframe class="dualooFrame"
                src="https://{portal_host}/portal/{portal_id}"></iframe>
            </div>
            """
        )
    return f"<html><body>{''.join(sections)}</body></html>"


def portal_card(
    portal_id: str,
    job_id: str,
    *,
    title: str,
    location: str = "GRITEC AG - Grüsch",
    category: str = "Mitarbeitende",
) -> str:
    return f"""
    <a class="jobElement" href="{portal_id}/{job_id}/detail?lang=DE">
      <span class="jobName">{title}</span>
      <span class="cityName">{location}</span>
      <span class="jobCategory">{category}</span>
    </a>
    """


def portal_html(portal_id: str, cards: list[str]) -> str:
    return f"""
    <html><body>
      <div class="JobInfoBox">{"".join(cards)}</div>
      <input id="jobPortalUrl" value="{portal_id}">
    </body></html>
    """


def detail_html(
    portal_id: str,
    job_id: str,
    *,
    title: str,
    locality: str = "Grüsch",
    country: str = "CH",
    employment_type: str = "FULL_TIME",
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-04-08T05:28:51Z",
        "employmentType": [employment_type],
        "description": "<p>Build modern industrial software.</p>",
        "responsibilities": "<ul><li>Develop applications</li></ul>",
        "skills": "<p>Python and C#</p>",
        "jobBenefits": "<p>Flexible working conditions.</p>",
        "hiringOrganization": {"@type": "Organization", "name": "GRITEC AG"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": locality,
                "addressCountry": country,
            },
        },
    }
    return f"""
    <html><body>
      <h1>{title}</h1>
      <a class="btn-apply" href="apply?lang=DE">Bewerben</a>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_gritec_collects_all_four_official_catalogs_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/career":
            return httpx.Response(200, text=career_html())
        if request.url.path == "/portal/oqmcwxep":
            return httpx.Response(
                200,
                text=portal_html(
                    "oqmcwxep",
                    [
                        portal_card(
                            "oqmcwxep",
                            SOFTWARE_ID,
                            title="Software Engineer",
                        )
                    ],
                ),
            )
        if request.url.path == "/portal/te8bsg7b":
            return httpx.Response(
                200,
                text=portal_html(
                    "te8bsg7b",
                    [
                        portal_card(
                            "te8bsg7b",
                            INITIATIVE_ID,
                            title="Initiativbewerbung",
                        )
                    ],
                ),
            )
        if request.url.path in {"/portal/04snstaz", "/portal/xfrw5a44"}:
            return httpx.Response(200, text=portal_html(request.url.path.rsplit("/", 1)[-1], []))
        if request.url.path.endswith(f"/{SOFTWARE_ID}/detail"):
            return httpx.Response(
                200,
                text=detail_html(
                    "oqmcwxep",
                    SOFTWARE_ID,
                    title="Software Engineer",
                ),
            )
        if request.url.path.endswith(f"/{INITIATIVE_ID}/detail"):
            return httpx.Response(
                200,
                text=detail_html(
                    "te8bsg7b",
                    INITIATIVE_ID,
                    title="Initiativbewerbung",
                    employment_type="OTHER",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    parser = GritecJobsParser(
        base_url="https://www.gritec.test/en/career",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )
    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert calls[:5] == [
        "/en/career",
        "/portal/oqmcwxep",
        "/portal/04snstaz",
        "/portal/xfrw5a44",
        "/portal/te8bsg7b",
    ]
    assert set(calls[5:]) == {
        f"/portal/oqmcwxep/{SOFTWARE_ID}/detail",
        f"/portal/te8bsg7b/{INITIATIVE_ID}/detail",
    }
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 GRITEC Switzerland opportunities from the official catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "gritec"
    assert first.title == "Software Engineer"
    assert first.company == "GRITEC AG"
    assert first.location == "Grüsch, Switzerland"
    assert first.url == (f"https://jobs.dualoo.com/portal/oqmcwxep/{SOFTWARE_ID}/detail?lang=DE")
    assert first.apply_url == (
        f"https://jobs.dualoo.com/portal/oqmcwxep/{SOFTWARE_ID}/apply?lang=DE"
    )
    assert first.posted_at == "2026-04-08T05:28:51Z"
    assert first.employment_type == "Full-time"
    assert first.description and "Build modern industrial software" in first.description
    assert first.description and "- Develop applications" in first.description
    assert first.raw["catalog_section"] == "vacancy"
    assert first.raw["detail"]["id"] == SOFTWARE_ID
    assert result.jobs[1].raw["catalog_section"] == "unsolicited"


def test_gritec_preserves_safe_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career":
            return httpx.Response(200, text=career_html())
        if request.url.path == "/portal/04snstaz":
            return httpx.Response(
                200,
                text=portal_html(
                    "04snstaz",
                    [
                        portal_card(
                            "04snstaz",
                            SOFTWARE_ID,
                            title="Lehrstelle Informatiker/in EFZ",
                            category="Lernende",
                        )
                    ],
                ),
            )
        if request.url.path in {
            "/portal/oqmcwxep",
            "/portal/xfrw5a44",
            "/portal/te8bsg7b",
        }:
            return httpx.Response(200, text=portal_html(request.url.path.rsplit("/", 1)[-1], []))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        GritecJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Lehrstelle Informatiker/in EFZ"
    assert job.company == "GRITEC AG"
    assert job.location == "Grüsch, Switzerland"
    assert job.apply_url == job.url
    assert job.employment_type == "Apprenticeship"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_gritec_rejects_missing_portal_or_non_swiss_catalog() -> None:
    missing = GritecJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text="<div class='node--type-stellenportal'>Jobs</div>",
            )
        )
    )

    def foreign_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career":
            return httpx.Response(200, text=career_html())
        portal_id = request.url.path.rsplit("/", 1)[-1]
        cards = (
            [portal_card(portal_id, SOFTWARE_ID, title="Engineer", location="Berlin")]
            if portal_id == "oqmcwxep"
            else []
        )
        return httpx.Response(200, text=portal_html(portal_id, cards))

    with pytest.raises(DirectCompanyRequestError, match="invalid job portal"):
        missing.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss opportunity"):
        GritecJobsParser(transport=httpx.MockTransport(foreign_handler)).search(
            LinkedInSearchRequest()
        )


def test_gritec_rejects_foreign_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career":
            return httpx.Response(200, text=career_html())
        if request.url.path == "/portal/oqmcwxep":
            return httpx.Response(
                200,
                text=portal_html(
                    "oqmcwxep",
                    [portal_card("oqmcwxep", SOFTWARE_ID, title="Software Engineer")],
                ),
            )
        if request.url.path in {
            "/portal/04snstaz",
            "/portal/xfrw5a44",
            "/portal/te8bsg7b",
        }:
            return httpx.Response(200, text=portal_html(request.url.path.rsplit("/", 1)[-1], []))
        return httpx.Response(
            200,
            text=detail_html(
                "oqmcwxep",
                SOFTWARE_ID,
                title="Software Engineer",
                locality="Berlin",
                country="DE",
            ),
        )

    job = (
        GritecJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Grüsch, Switzerland"
    assert job.description is None
    assert "non-Swiss opportunity" in str(job.raw["detail_error"])


def test_gritec_wraps_listing_request_failures() -> None:
    parser = GritecJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_gritec_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["gritec"]
    assert isinstance(parser, GritecJobsParser)
    assert parser.base_url == settings.gritec_jobs_base_url
    assert parser.detail_workers == settings.gritec_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "GRITEC", "filters": {}},
            "sources": ["gritec", "gritec"],
        }
    )
    assert request.sources == ["gritec"]


def test_gritec_jobs_render_as_direct_company_imports() -> None:
    job = GritecJobsParser().normalize_job(
        {
            "id": SOFTWARE_ID,
            "portal_id": "oqmcwxep",
            "title": "Software Engineer",
            "location": "GRITEC AG - Grüsch",
            "catalog_section": "vacancy",
            "url": (f"https://jobs.dualoo.com/portal/oqmcwxep/{SOFTWARE_ID}/detail?lang=DE"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"gritec-{SOFTWARE_ID}",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "jobs.dualoo.com"
    assert stored["logo"] == "company"
    assert stored["department"] == "GRITEC import"
    assert stored["id"] == f"gritec-{SOFTWARE_ID}"
