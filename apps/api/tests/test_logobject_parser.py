from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.logobject import LogObjectJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(*, path: str, title: str, location: str) -> str:
    return f"""
    <div class="career-item">
      <a class="absolute-link" href="{path}" title="{title}">&nbsp;</a>
      <div class="career-title"><span>{title}</span></div>
      <div class="career-subtitle"><span>{location}</span></div>
    </div>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><body><main>
      <section class="section--career">
        <h2>Aktuelle Stellenangebote</h2>
        <div class="career-list">{"".join(cards)}</div>
      </section>
    </main></body></html>
    """


def detail_html(
    *,
    path: str,
    title: str,
    og_title: str | None = None,
    apply_email: str = "jobs@logobject.ch",
) -> str:
    return f"""
    <html><head>
      <link rel="canonical" href="https://logobject.test{path}">
      <meta property="og:title" content="{og_title or title}">
    </head><body><main>
      <section class="section-header"><h1>{title}</h1></section>
      <nav><li class="breadcrumb-item current">{title}</li></nav>
      <section class="section--intro">
        <div class="frame-type-text">
          <h2>Meistere komplexe Systeme.</h2>
          <p>Zur Verstärkung unseres Teams in Zürich suchen wir Dich.</p>
        </div>
      </section>
      <section class="section-text">
        <div class="frame-type-text">
          <h2>Dein Aufgabenbereich</h2>
          <ul><li>Entwickle Java-Software</li><li>Optimiere Prozesse</li></ul>
        </div>
        <div class="frame-type-text">
          <h2>Was Du mitbringst</h2><p>Erfahrung mit relationalen Datenbanken.</p>
        </div>
      </section>
      <section class="section-contact">
        <h2>Bist Du die/der Richtige für uns?</h2>
        <a href="mailto:{apply_email}">{apply_email}</a>
      </section>
    </main></body></html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            path="/karriere/wirtschaftsinformatiker-software-entwicklung-m/w/d-1",
            title="Wirtschaftsinformatiker Software Entwicklung (m/w/d)",
            location="Zürich (Schweiz)",
        ),
        listing_card(
            path="/karriere/security-officer-m/w/d",
            title="Security Officer 60%-100% (m/w/d)",
            location="Zürich (Schweiz)",
        ),
        listing_card(
            path="/karriere/business-analyst/technischer-projektleiter-m/w/d",
            title="Business Analyst/technischer Projektleiter (m/w/d)",
            location="Oberhausen (Deutschland)",
        ),
    ]


def test_logobject_collects_complete_swiss_subset_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/karriere":
            return httpx.Response(200, text=listing_html(catalog_fixture()))
        if request.url.path.endswith("/wirtschaftsinformatiker-software-entwicklung-m/w/d-1"):
            return httpx.Response(
                200,
                text=detail_html(
                    path=request.url.path,
                    title="Wirtschaftsinformatiker Software Entwicklung (m/w/d)",
                    og_title="WirtschaftsinformatikerIn Software Entwicklung (100%) | LogObject",
                ),
            )
        if request.url.path.endswith("/security-officer-m/w/d"):
            return httpx.Response(
                200,
                text=detail_html(
                    path=request.url.path,
                    title="Security Officer 60%-100% (m/w/d)",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    parser = LogObjectJobsParser(
        base_url="https://logobject.test/karriere",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )
    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert calls[0] == "/karriere"
    assert set(calls[1:]) == {
        "/karriere/wirtschaftsinformatiker-software-entwicklung-m/w/d-1",
        "/karriere/security-officer-m/w/d",
    }
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 LogObject Switzerland vacancies from the complete official catalog"
    )
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "logobject"
    assert first.title == "Wirtschaftsinformatiker Software Entwicklung (m/w/d)"
    assert first.company == "LogObject AG"
    assert first.location == "Zürich, Switzerland"
    assert first.url == (
        "https://logobject.test/karriere/"
        "wirtschaftsinformatiker-software-entwicklung-m/w/d-1"
    )
    assert first.apply_url == "mailto:jobs@logobject.ch"
    assert first.employment_type == "100%"
    assert first.description and "Meistere komplexe Systeme" in first.description
    assert first.description and "- Entwickle Java-Software" in first.description
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["id"] == (
        "wirtschaftsinformatiker-software-entwicklung-m-w-d-1"
    )
    assert result.jobs[1].employment_type == "60-100%"


def test_logobject_preserves_safe_listing_when_detail_fails() -> None:
    card = listing_card(
        path="/karriere/security-officer-m/w/d",
        title="Security Officer (m/w/d)",
        location="Zürich (Schweiz)",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere":
            return httpx.Response(200, text=listing_html([card]))
        return httpx.Response(503)

    job = (
        LogObjectJobsParser(
            base_url="https://logobject.test/karriere",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "page, message",
    [
        ("<html><main></main></html>", "missing its vacancy catalog"),
        (
            listing_html(
                [
                    listing_card(
                        path="/karriere/engineer",
                        title="Engineer",
                        location="Paris (Frankreich)",
                    )
                ]
            ),
            "unknown country",
        ),
        (
            listing_html(
                [
                    listing_card(
                        path="https://evil.test/karriere/engineer",
                        title="Engineer",
                        location="Zürich (Schweiz)",
                    )
                ]
            ),
            "incomplete vacancy",
        ),
    ],
)
def test_logobject_rejects_invalid_catalog(page: str, message: str) -> None:
    parser = LogObjectJobsParser(
        base_url="https://logobject.test/karriere",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_logobject_enforces_catalog_limit() -> None:
    parser = LogObjectJobsParser(
        base_url="https://logobject.test/karriere",
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(catalog_fixture()))
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_logobject_rejects_mismatched_detail_but_keeps_listing() -> None:
    card = listing_card(
        path="/karriere/security-officer-m/w/d",
        title="Security Officer (m/w/d)",
        location="Zürich (Schweiz)",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere":
            return httpx.Response(200, text=listing_html([card]))
        return httpx.Response(
            200,
            text=detail_html(
                path=request.url.path,
                title="Different vacancy",
            ),
        )

    job = (
        LogObjectJobsParser(
            base_url="https://logobject.test/karriere",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description is None
    assert "different vacancy title" in str(job.raw["detail_error"])


def test_logobject_wraps_listing_request_failures() -> None:
    parser = LogObjectJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_logobject_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["logobject"]
    assert isinstance(parser, LogObjectJobsParser)
    assert parser.base_url == settings.logobject_jobs_base_url
    assert parser.max_jobs == settings.logobject_jobs_max_jobs
    assert parser.detail_workers == settings.logobject_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "LogObject", "filters": {}},
            "sources": ["logobject", "logobject"],
        }
    )
    assert request.sources == ["logobject"]


def test_logobject_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": "security-officer-m-w-d",
        "title": "Security Officer (m/w/d)",
        "location": "Zürich, Switzerland",
        "url": "https://logobject.com/karriere/security-officer-m/w/d",
    }
    parsed = LogObjectJobsParser().normalize_job(record)

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="logobject-security-officer-m-w-d",
        added_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "logobject-security-officer-m-w-d"
    assert stored["logo"] == "company"
    assert stored["department"] == "LogObject import"
    assert stored["company"] == "LogObject AG"
