from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.prodyna_switzerland import (
    ProdynaSwitzerlandJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.prodyna.com/jobs?location=Zurich"
CATALOG_URL = "https://www.prodyna.com/jobs"
RSS_URL = "https://www.prodyna.com/jobs/rss.xml"


def listing_card(
    slug: str,
    *,
    title: str,
    division: str = "PRODYNA - Switzerland",
    category: str = "IT-Consulting &amp; Engineering",
    location: str = "Zurich",
) -> str:
    return f"""
    <div class="open-position-link">
      <h2 fs-cmsfilter-field="name">{title}</h2>
      <div fs-cmsfilter-field="division">{division}</div>
      <div fs-cmsfilter-field="category">{category}</div>
      <div fs-cmsfilter-field="location">{location}</div>
      <a href="/jobs/{slug}" class="open-position-absolute-link"></a>
    </div>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><head><link rel="canonical" href="{CATALOG_URL}"></head>
    <body>{"".join(cards)}</body></html>
    """


def rss_xml(items: list[tuple[str, str, str]]) -> str:
    rendered = "".join(
        f"""
        <item>
          <title>{title} | PRODYNA</title>
          <link>https://www.prodyna.com/jobs/{slug}</link>
          <guid>https://www.prodyna.com/jobs/{slug}</guid>
          <pubDate>{published}</pubDate>
        </item>
        """
        for slug, title, published in items
    )
    return f"""
    <rss version="2.0"><channel>
      <title>PRODYNA Careers</title><link>https://www.prodyna.com</link>
      {rendered}
    </channel></rss>
    """


def metadata_item(label: str, values: list[str]) -> str:
    if len(values) == 1:
        body = values[0]
    else:
        body = (
            '<div class="jobs-meta-collection-item">'
            + ('</div><div class="jobs-meta-collection-item">'.join(values))
            + "</div>"
        )
    return f'<div class="meta-item"><div>{label}</div><div>{body}</div></div>'


def detail_html(
    slug: str,
    *,
    title: str,
    division: str = "PRODYNA - Switzerland",
    location: str = "Zurich",
    vacancy_id: str = "673",
    canonical_slug: str | None = None,
) -> str:
    canonical = canonical_slug or slug
    metadata = "".join(
        [
            metadata_item("Division", [division]),
            metadata_item("Location", [location]),
            metadata_item("Seniority Level", ["Junior", "Professional", "Senior"]),
            metadata_item("Category", ["IT-Consulting &amp; Engineering"]),
            metadata_item("Workload", ["100%"]),
            metadata_item("Language", ["German"]),
        ]
    )
    return f"""
    <html><head>
      <link rel="canonical" href="https://www.prodyna.com/jobs/{canonical}">
      <meta property="og:title" content="{title} | PRODYNA">
    </head><body>
      <h1>{title}</h1>
      {metadata}
      <div class="job-description">
        <p>Build secure Azure platforms for our clients.</p>
        <h2>Your tasks</h2>
        <ul><li>Implement landing zones.</li><li>Guide client teams.</li></ul>
        <h2>Your profile</h2><ul><li>Strong cloud experience.</li></ul>
      </div>
      <a href="https://jobs.prodyna.com/Vacancies/{vacancy_id}/Application/CheckLogin/2?lang=eng">Apply now</a>
    </body></html>
    """


def catalog_fixture() -> tuple[list[str], list[tuple[str, str, str]]]:
    cards = [
        listing_card(
            "zurich-azure-platform-engineer",
            title="Azure Platform Engineer (all genders)",
        ),
        listing_card(
            "cloud-architect-basel",
            title="Cloud Architect (all genders)",
            location="Basel",
        ),
        listing_card(
            "berlin-software-architect",
            title="Software Architect (all genders)",
            division="PRODYNA - Germany",
            location="Berlin",
        ),
    ]
    items = [
        (
            "zurich-azure-platform-engineer",
            "Azure Platform Engineer (all genders)",
            "Mon, 02 Feb 2026 12:51:18 GMT",
        ),
        (
            "cloud-architect-basel",
            "Cloud Architect (all genders)",
            "Mon, 06 Jul 2026 10:27:23 GMT",
        ),
        (
            "berlin-software-architect",
            "Software Architect (all genders)",
            "Fri, 30 Jan 2026 10:33:31 GMT",
        ),
    ]
    return cards, items


def test_prodyna_collects_reconciled_catalog_and_enriches_zurich_jobs() -> None:
    cards, items = catalog_fixture()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(cards), request=request)
        if request.url.path == "/jobs/rss.xml":
            return httpx.Response(200, text=rss_xml(items), request=request)
        return httpx.Response(
            200,
            text=detail_html(
                "zurich-azure-platform-engineer",
                title="Azure Platform Engineer (all genders)",
            ),
            request=request,
        )

    result = ProdynaSwitzerlandJobsParser(
        base_url=BASE_URL,
        rss_url=RSS_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == ["/jobs", "/jobs/rss.xml", "/jobs/zurich-azure-platform-engineer"]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 1 PRODYNA Zurich vacancies from 3 reconciled global catalog records"
    )
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "prodyna_switzerland"
    assert job.title == "Azure Platform Engineer (all genders)"
    assert job.company == "PRODYNA (Schweiz) AG"
    assert job.location == "Zurich, Switzerland"
    assert job.url == "https://www.prodyna.com/jobs/zurich-azure-platform-engineer"
    assert job.apply_url == (
        "https://jobs.prodyna.com/Vacancies/673/Application/CheckLogin/2?lang=eng"
    )
    assert job.posted_at == "2026-02-02"
    assert job.employment_type == "100%"
    assert job.seniority == "Junior, Professional, Senior"
    assert job.description == (
        "Build secure Azure platforms for our clients.\n\n"
        "Your tasks\n- Implement landing zones.\n- Guide client teams.\n\n"
        "Your profile\n- Strong cloud experience."
    )
    assert job.raw["rss"]["posted_at"] == "2026-02-02"


def test_prodyna_preserves_strict_listing_when_detail_fails() -> None:
    cards = [listing_card("zurich-full-stack", title="Full Stack Engineer")]
    items = [
        (
            "zurich-full-stack",
            "Full Stack Engineer",
            "Thu, 02 Nov 2023 13:13:38 GMT",
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(cards), request=request)
        if request.url.path == "/jobs/rss.xml":
            return httpx.Response(200, text=rss_xml(items), request=request)
        return httpx.Response(503, request=request)

    job = (
        ProdynaSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Full Stack Engineer"
    assert job.location == "Zurich, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at == "2023-11-02"
    assert job.employment_type is None
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_prodyna_rejects_html_rss_drift_and_invalid_zurich_division() -> None:
    card = listing_card("zurich-full-stack", title="Full Stack Engineer")
    wrong_items = [
        (
            "zurich-other-role",
            "Other Role",
            "Thu, 02 Nov 2023 13:13:38 GMT",
        )
    ]

    def drift_handler(request: httpx.Request) -> httpx.Response:
        body = listing_html([card]) if request.url.path == "/jobs" else rss_xml(wrong_items)
        return httpx.Response(200, text=body, request=request)

    with pytest.raises(DirectCompanyRequestError, match="different vacancies"):
        ProdynaSwitzerlandJobsParser(transport=httpx.MockTransport(drift_handler)).search(
            LinkedInSearchRequest()
        )

    invalid_card = listing_card(
        "zurich-full-stack",
        title="Full Stack Engineer",
        division="PRODYNA - Germany",
    )
    valid_items = [
        (
            "zurich-full-stack",
            "Full Stack Engineer",
            "Thu, 02 Nov 2023 13:13:38 GMT",
        )
    ]

    def division_handler(request: httpx.Request) -> httpx.Response:
        body = listing_html([invalid_card]) if request.url.path == "/jobs" else rss_xml(valid_items)
        return httpx.Response(200, text=body, request=request)

    with pytest.raises(DirectCompanyRequestError, match="unexpected division"):
        ProdynaSwitzerlandJobsParser(transport=httpx.MockTransport(division_handler)).search(
            LinkedInSearchRequest()
        )


def test_prodyna_rejects_catalog_limit_and_mismatched_detail() -> None:
    cards, items = catalog_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        body = listing_html(cards) if request.url.path == "/jobs" else rss_xml(items)
        return httpx.Response(200, text=body, request=request)

    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        ProdynaSwitzerlandJobsParser(
            max_catalog_records=2,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html(
                "zurich-azure-platform-engineer",
                title="Azure Platform Engineer (all genders)",
            ),
            page_url="https://www.prodyna.com/jobs/zurich-azure-platform-engineer",
            expected_url="https://www.prodyna.com/jobs/cloud-architect-zurich",
            expected_slug="cloud-architect-zurich",
            expected_title="Cloud Architect (all genders)",
            expected_division="PRODYNA - Switzerland",
            expected_location="Zurich",
        )


def test_prodyna_wraps_listing_request_failures() -> None:
    parser = ProdynaSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_prodyna_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["prodyna_switzerland"]
    assert isinstance(parser, ProdynaSwitzerlandJobsParser)
    assert parser.base_url == settings.prodyna_switzerland_jobs_base_url
    assert parser.rss_url == settings.prodyna_switzerland_jobs_rss_url
    assert parser.max_catalog_records == (settings.prodyna_switzerland_jobs_max_catalog_records)
    assert parser.detail_workers == settings.prodyna_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "PRODYNA", "filters": {}},
            "sources": ["prodyna_switzerland", "prodyna_switzerland"],
        }
    )
    assert request.sources == ["prodyna_switzerland"]


def test_prodyna_jobs_render_as_direct_company_imports() -> None:
    job = ProdynaSwitzerlandJobsParser().normalize_job(
        {
            "id": "zurich-full-stack",
            "title": "Full Stack Software Engineer (all genders)",
            "division": "PRODYNA - Switzerland",
            "category": "IT-Consulting & Engineering",
            "location": "Zurich",
            "url": "https://www.prodyna.com/jobs/zurich-full-stack",
            "rss": {"posted_at": "2023-11-02"},
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="prodyna_switzerland-zurich-full-stack",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "PRODYNA Switzerland import"
    assert stored["id"] == "prodyna_switzerland-zurich-full-stack"
