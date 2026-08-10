from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.helbling import HelblingJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

APPLY_URL = (
    "https://app.jobportal.abaservices.ch/application-process/"
    "ce984096-e44e-479a-947c-a733685d6447/"
    "47a2aea7-6810-4a55-30c9-f286025b88c7"
)
SAFE_APPLY_URL = (
    f"https://eur03.safelinks.protection.outlook.com/?url={quote(APPLY_URL, safe='')}&data=opaque"
)


def listing_card(
    job_id: str,
    *,
    slug: str,
    title: str,
    location: str,
    area: str = "Technik",
    workload: str = "100 %",
    employment_kind: str = "PermanentPosition",
    posted_at: str = "20260806",
) -> str:
    tags = html.escape(
        json.dumps(
            {
                "area": area.casefold(),
                "location": location,
                "employmentRange": workload.replace(" ", "").replace("%", ""),
                "type": employment_kind,
            }
        ),
        quote=True,
    )
    return f"""
    <li class="jobsearch-item" data-tags="{tags}">
      <a href="/de/karriere/jobs/{slug}">
        <h2 class="title">{title}</h2>
        <p class="display-overline">{area}</p>
        <span class="pensum">{workload}</span>
        <span class="ident">{job_id}</span>
        <div class="date">{posted_at}</div>
      </a>
    </li>
    """


def listing_html(cards: list[str], *, declared_total: int | None = None) -> str:
    total = len(cards) if declared_total is None else declared_total
    return f"""
    <html><body>
      <span class="js-list-count">{total}</span>
      <span x-html="itemsTotal">{total}</span>
      <ul>{"".join(cards)}</ul>
    </body></html>
    """


def detail_html(
    job_id: str,
    *,
    primary_title: str,
    subtitle: str = "",
    contact_location: str = "Liebefeld-Bern",
    apply_url: str = APPLY_URL,
) -> str:
    breadcrumb = {
        "@context": "https://schema.org/",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Jobs"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": f"[{job_id}] : {primary_title}",
            },
        ],
    }
    return f"""
    <html><body><main>
      <div class="m-hero-level-3">
        <h1>{primary_title}</h1><h2>{subtitle}</h2>
      </div>
      <div class="two-column-content">
        <div>
          <div class="c-bodytext">
            <p>Helbling develops innovative products.</p>
            <ul><li>Build embedded software</li><li>Work with customers</li></ul>
          </div>
          <p class="nodetype-element--jvmtech-base-content-headline--joblead">
            Innovating a sustainable future!
          </p>
        </div>
        <div class="contact-box">
          <p><strong>{contact_location}</strong></p>
          <a class="c-button" href="{apply_url}">Jetzt bewerben</a>
        </div>
      </div>
      <script type="application/ld+json">{json.dumps(breadcrumb)}</script>
    </main></body></html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "1167",
            slug="1167-embedded-software-engineer",
            title="Embedded Software Engineer / Consumer Electronics & Applied AI",
            location="Bern",
        ),
        listing_card(
            "1163",
            slug="1163-business-solution-architect",
            title="Business Solution Architect – AI, Cloud & UX (Uni / FH)",
            location="Aarau",
            workload="80 - 100 %",
        ),
        listing_card(
            "1180",
            slug="praktikant-m-w-d",
            title="Praktikant (m/w/d)",
            location="Dusseldorf",
            area="Business Advisors",
            employment_kind="Internship",
        ),
    ]


def test_helbling_collects_complete_swiss_subset_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/de/karriere/jobs":
            return httpx.Response(200, text=listing_html(catalog_fixture()))
        if request.url.path.endswith("1167-embedded-software-engineer"):
            return httpx.Response(
                200,
                text=detail_html(
                    "1167",
                    primary_title="Embedded Software Engineer",
                    subtitle="Consumer Electronics & Applied AI",
                ),
            )
        if request.url.path.endswith("1163-business-solution-architect"):
            return httpx.Response(
                200,
                text=detail_html(
                    "1163",
                    primary_title="Business Solution Architect – AI, Cloud & UX (Uni / FH)",
                    contact_location="Aarau",
                    apply_url=SAFE_APPLY_URL,
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = HelblingJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls[0] == "/de/karriere/jobs"
    assert set(calls[1:]) == {
        "/de/karriere/jobs/1167-embedded-software-engineer",
        "/de/karriere/jobs/1163-business-solution-architect",
    }
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Helbling Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "helbling"
    assert first.title == ("Embedded Software Engineer / Consumer Electronics & Applied AI")
    assert first.company == "Helbling"
    assert first.location == "Bern, Switzerland"
    assert first.url == ("https://helbling.ch/de/karriere/jobs/1167-embedded-software-engineer")
    assert first.apply_url == APPLY_URL
    assert first.posted_at == "2026-08-06"
    assert first.employment_type == "Permanent · 100 %"
    assert first.description and "Helbling develops innovative products" in first.description
    assert first.description and "- Build embedded software" in first.description
    assert first.raw["area"] == "Technik"
    assert first.raw["detail"]["id"] == "1167"
    assert result.jobs[1].location == "Aarau, Switzerland"
    assert all(job.raw["id"] != "1180" for job in result.jobs)


def test_helbling_preserves_safe_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/karriere/jobs":
            return httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "1167",
                            slug="1167-embedded-software-engineer",
                            title="Embedded Software Engineer",
                            location="Bern",
                        )
                    ]
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        HelblingJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Embedded Software Engineer"
    assert job.company == "Helbling"
    assert job.location == "Bern, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_helbling_rejects_incomplete_catalog_or_unknown_location() -> None:
    count_mismatch = HelblingJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), declared_total=4),
            )
        )
    )
    unknown_location = HelblingJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "1200",
                            slug="unknown-location",
                            title="Engineer",
                            location="Paris",
                        )
                    ]
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="declared 4"):
        count_mismatch.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="unknown location"):
        unknown_location.search(LinkedInSearchRequest())


def test_helbling_rejects_mismatched_or_non_swiss_detail_but_keeps_listing() -> None:
    responses = iter(
        [
            detail_html(
                "9999",
                primary_title="Different vacancy",
            ),
            detail_html(
                "1167",
                primary_title="Embedded Software Engineer",
                contact_location="Düsseldorf",
            ),
        ]
    )

    def run_once(detail: str):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/de/karriere/jobs":
                return httpx.Response(
                    200,
                    text=listing_html(
                        [
                            listing_card(
                                "1167",
                                slug="1167-embedded-software-engineer",
                                title="Embedded Software Engineer",
                                location="Bern",
                            )
                        ]
                    ),
                )
            return httpx.Response(200, text=detail)

        return (
            HelblingJobsParser(transport=httpx.MockTransport(handler))
            .search(LinkedInSearchRequest())
            .jobs[0]
        )

    mismatched = run_once(next(responses))
    foreign = run_once(next(responses))

    assert mismatched.description is None
    assert "different vacancy" in str(mismatched.raw["detail_error"])
    assert foreign.location == "Bern, Switzerland"
    assert foreign.description is None
    assert "non-Swiss vacancy" in str(foreign.raw["detail_error"])


def test_helbling_wraps_listing_request_failures() -> None:
    parser = HelblingJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_helbling_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["helbling"]
    assert isinstance(parser, HelblingJobsParser)
    assert parser.base_url == settings.helbling_jobs_base_url
    assert parser.detail_workers == settings.helbling_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Helbling", "filters": {}},
            "sources": ["helbling", "helbling"],
        }
    )
    assert request.sources == ["helbling"]


def test_helbling_jobs_render_as_direct_company_imports() -> None:
    job = HelblingJobsParser().normalize_job(
        {
            "id": "1167",
            "title": "Embedded Software Engineer",
            "area": "Technik",
            "location_code": "Bern",
            "workload": "100 %",
            "employment_kind": "PermanentPosition",
            "posted_at": "2026-08-06",
            "url": ("https://helbling.ch/de/karriere/jobs/1167-embedded-software-engineer"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="helbling-1167",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "helbling.ch"
    assert stored["logo"] == "company"
    assert stored["department"] == "Helbling import"
    assert stored["id"] == "helbling-1167"
