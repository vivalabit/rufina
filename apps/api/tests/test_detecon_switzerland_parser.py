from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.detecon_switzerland import (
    DeteconSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOBS_URL = "https://www.detecon.com/de/jobs"
AI_SLUG = "student-consultant-applied-agentic-ai-entwicklung-all-genders"


def job_url(slug: str) -> str:
    return f"https://www.detecon.com/de/job/{slug}"


def card(*, title: str, slug: str, location: str = "Zürich") -> str:
    return f"""
    <div class="eael-post-list-post eael-empty-thumbnail">
      <div class="eael-post-list-content">
        <h2 class="eael-post-list-title"><a href="{job_url(slug)}">{title}</a></h2>
        <p>Unterstütze unsere Consultants bei anspruchsvollen Projekten.</p>
        <a class="eael-post-elements-readmore-btn" href="{job_url(slug)}">Weiterlesen</a>
        <div class="meta-cats-wrap"><a href="/?term=zurich">⚲ {location}</a></div>
      </div>
    </div>
    """


def listing_html(cards: str, *, foreign_card: str = "") -> str:
    return f"""
    <html><body>
      <div id="deutschland-tab">
        <div class="eael-post-list-posts-wrap">{foreign_card}</div>
      </div>
      <div id="schweiz-tab" class="eael-tab-content-item inactive">
        <div class="eael-post-list-posts-wrap">{cards}</div>
      </div>
    </body></html>
    """


def detail_html(*, title: str, slug: str, email: str = "recruiting-alpine@detecon.com") -> str:
    return f"""
    <html><head>
      <link rel="canonical" href="{job_url(slug)}/" />
      <meta name="stc:post-type" content="job" />
    </head><body>
      <div data-widget_type="theme-post-title.default">
        <h1 class="elementor-heading-title">{title}</h1>
      </div>
      <div data-elementor-post-type="job">
        <p>Digital First – wir begleiten unsere Kund*innen.</p>
        <h2>Was dich bei uns erwartet</h2>
        <ul><li><span class="elementor-icon-list-text">Entwicklung mit Python</span></li></ul>
        <h2>Bereit für Detecon?</h2>
        <p>Du studierst Informatik.</p>
        <a href="mailto:{email}">Jetzt bewerben</a>
      </div>
    </body></html>
    """


def official_cards() -> str:
    return "".join(
        [
            card(
                title="Student Consultant – Applied / Agentic AI Entwicklung (all genders)",
                slug=AI_SLUG,
            ),
            card(
                title="Senior Consultant Cloud Strategy (all genders)",
                slug="senior-consultant-cloud-strategy-all-genders",
            ),
        ]
    )


def test_detecon_collects_complete_swiss_catalog_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/de/jobs":
            return httpx.Response(
                200,
                text=listing_html(
                    official_cards(),
                    foreign_card=card(
                        title="Consultant in Deutschland",
                        slug="consultant-in-deutschland",
                        location="Berlin",
                    ),
                ),
            )
        slug = request.url.path.rsplit("/", 1)[-1]
        titles = {
            AI_SLUG: "Student Consultant – Applied / Agentic AI Entwicklung (all genders)",
            "senior-consultant-cloud-strategy-all-genders": (
                "Senior Consultant Cloud Strategy (all genders)"
            ),
        }
        return httpx.Response(200, text=detail_html(title=titles[slug], slug=slug))

    result = DeteconSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Detecon Switzerland vacancies from the complete official catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "detecon_switzerland"
    assert first.title == "Student Consultant – Applied / Agentic AI Entwicklung (all genders)"
    assert first.company == "Detecon (Schweiz) AG"
    assert first.location == "Zürich, Switzerland"
    assert first.url == job_url(AI_SLUG)
    assert first.apply_url == "mailto:recruiting-alpine@detecon.com"
    assert first.posted_at is None
    assert first.employment_type is None
    assert first.seniority is None
    assert first.description and "Digital First" in first.description
    assert first.description and "- Entwicklung mit Python" in first.description
    assert first.raw["id"] == AI_SLUG
    assert first.raw["detail"]["public_url"] == job_url(AI_SLUG)


def test_detecon_preserves_safe_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs":
            return httpx.Response(
                200,
                text=listing_html(
                    card(
                        title=(
                            "Student Consultant – Applied / Agentic AI Entwicklung "
                            "(all genders)"
                        ),
                        slug=AI_SLUG,
                    )
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        DeteconSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Student Consultant – Applied / Agentic AI Entwicklung (all genders)"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description == "Unterstütze unsere Consultants bei anspruchsvollen Projekten."
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "page_html,error",
    [
        ("<html></html>", "Switzerland catalog tab"),
        (
            '<div id="schweiz-tab"></div>',
            "Switzerland vacancy catalog",
        ),
        (
            listing_html(
                card(
                    title="Consultant",
                    slug="consultant",
                    location="Berlin",
                )
            ),
            "unexpected location",
        ),
    ],
)
def test_detecon_rejects_malformed_or_non_swiss_catalog(
    page_html: str,
    error: str,
) -> None:
    parser = DeteconSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page_html))
    )

    with pytest.raises(DirectCompanyRequestError, match=error):
        parser.search(LinkedInSearchRequest())


def test_detecon_rejects_mismatched_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs":
            return httpx.Response(
                200,
                text=listing_html(
                    card(
                        title="Student Consultant – Applied / Agentic AI Entwicklung (all genders)",
                        slug=AI_SLUG,
                    )
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(title="Different vacancy", slug=AI_SLUG),
        )

    job = (
        DeteconSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description == "Unterstütze unsere Consultants bei anspruchsvollen Projekten."
    assert "different vacancy title" in str(job.raw["detail_error"])


def test_detecon_accepts_an_empty_official_swiss_catalog() -> None:
    parser = DeteconSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(""))
        )
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Detecon Switzerland vacancies from the complete official catalog"
    )


def test_detecon_wraps_listing_request_failures() -> None:
    parser = DeteconSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(503, text="unavailable")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_detecon_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["detecon_switzerland"]
    assert isinstance(parser, DeteconSwitzerlandJobsParser)
    assert parser.base_url == settings.detecon_switzerland_jobs_base_url
    assert parser.detail_workers == settings.detecon_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Detecon Switzerland", "filters": {}},
            "sources": ["detecon_switzerland", "detecon_switzerland"],
        }
    )
    assert request.sources == ["detecon_switzerland"]


def test_detecon_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": AI_SLUG,
        "title": "Student Consultant – Applied / Agentic AI Entwicklung (all genders)",
        "location": "Zürich, Switzerland",
        "url": job_url(AI_SLUG),
        "teaser": "Unterstütze unsere Consultants.",
    }
    job = DeteconSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"detecon_switzerland-{AI_SLUG}",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "www.detecon.com"
    assert stored["logo"] == "company"
    assert stored["department"] == "Detecon Switzerland import"
    assert stored["id"] == f"detecon_switzerland-{AI_SLUG}"
