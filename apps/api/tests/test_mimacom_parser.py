from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.mimacom import MimacomJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(
    *,
    slug: str,
    title: str,
    location: str = "Zurich,Bern",
    category: str = "Engineering",
    employment: str = "Full time",
) -> str:
    return f"""
    <li data-location="{location}" data-category="{category}"
        data-employment="{employment}">
      <div class="job_content">
        <div class="job_title"><h4>{title}</h4></div>
      </div>
      <div class="inner_page_link">
        <a href="https://www.mimacom.test/jobs/{slug}?hsLang=en"></a>
      </div>
    </li>
    """


def listing_html(cards: list[str], *, declared_total: int | None = None) -> str:
    total = len(cards) if declared_total is None else declared_total
    return f"""
    <html><body>
      <div class="joblist_wrapper">
        <div class="search_result">{total} jobs found</div>
        <div class="tablist"><ul>{"".join(cards)}</ul></div>
      </div>
    </body></html>
    """


def detail_html(
    *,
    slug: str,
    title: str,
    workday_id: str,
    location: str = "Zurich, Bern",
    employment: str = "Full time",
    apply_suffix: str = "",
) -> str:
    return f"""
    <html><head>
      <meta property="og:url" content="https://www.mimacom.test/jobs/{slug}">
    </head><body>
      <div class="job_detail_new" data-attr="Job Detail Header 2026">
        <div class="job_detail_header_btn">
          <a href="https://flowable.wd502.myworkdayjobs.com/mimacom/job/Zurich-Test/{slug}_{workday_id}{apply_suffix}">
            Apply now
          </a>
        </div>
        <div class="job_detail_hero">
          <h1>{title}</h1>
          <div class="job_detail_hero_box">
            <ul>
              <li><span class="text">{location}</span></li>
              <li><span class="text">{employment}</span></li>
            </ul>
          </div>
        </div>
        <div class="job_detail_card_box">
          <h3>What We’re About</h3>
          <div class="job_detail_description">
            <p>Build reliable digital platforms.</p>
          </div>
        </div>
        <div class="job_detail_card_box">
          <h3>What You’ll Do</h3>
          <div class="job_detail_description">
            <ul><li>Own cloud services</li><li>Coach engineers</li></ul>
          </div>
        </div>
      </div>
    </body></html>
    """


def test_mimacom_scans_and_enriches_complete_catalog() -> None:
    cards = [
        listing_card(
            slug="senior-java-engineer",
            title="Senior Java Engineer (80-100%, m/f/d)",
        ),
        listing_card(
            slug="sales-executive",
            title="Sales Executive (m/f/d)",
            category="Sales",
        ),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(cards))
        if request.url.path == "/jobs/senior-java-engineer":
            return httpx.Response(
                200,
                text=detail_html(
                    slug="senior-java-engineer",
                    title="Senior Java Engineer (80-100%, m/f/d)",
                    workday_id="JR100989",
                    apply_suffix="/apply/autofillWithResume",
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                slug="sales-executive",
                title="Sales Executive (m/f/d)",
                workday_id="JR100990",
            ),
        )

    parser = MimacomJobsParser(
        base_url="https://www.mimacom.test/jobs",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Mimacom vacancies from the full HubSpot catalog with detail enrichment"
    )
    assert len(requests) == 3
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "mimacom"
    assert first.title == "Senior Java Engineer (80-100%, m/f/d)"
    assert first.company == "Mimacom"
    assert first.location == "Zurich, Bern"
    assert first.url == "https://www.mimacom.test/jobs/senior-java-engineer"
    assert first.apply_url == (
        "https://flowable.wd502.myworkdayjobs.com/mimacom/job/"
        "Zurich-Test/senior-java-engineer_JR100989/apply/autofillWithResume"
    )
    assert first.posted_at is None
    assert first.employment_type == "80-100%"
    assert first.seniority == "Senior"
    assert first.description == (
        "What We’re About\nBuild reliable digital platforms.\n\n"
        "What You’ll Do\n- Own cloud services\n- Coach engineers"
    )
    assert first.raw["id"] == "senior-java-engineer"
    assert first.raw["total_available"] == 2
    assert first.raw["detail"]["workday_job_id"] == "JR100989"
    assert result.jobs[1].employment_type == "Full time"
    assert result.jobs[1].seniority is None


def test_mimacom_preserves_listing_when_detail_fails() -> None:
    card = listing_card(slug="sales-executive", title="Sales Executive (m/f/d)")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html([card]))
        return httpx.Response(503)

    job = (
        MimacomJobsParser(
            base_url="https://www.mimacom.test/jobs",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Sales Executive (m/f/d)"
    assert job.location == "Zurich, Bern"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_mimacom_rejects_catalog_count_mismatch() -> None:
    page = listing_html(
        [listing_card(slug="sales-executive", title="Sales Executive")],
        declared_total=2,
    )
    parser = MimacomJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="count does not match"):
        parser.search(LinkedInSearchRequest())


def test_mimacom_rejects_incomplete_catalog() -> None:
    page = listing_html(
        [
            """
            <li data-location="Zurich" data-category="Engineering"
                data-employment="Full time">
              <div class="job_title"><h4>Engineer</h4></div>
            </li>
            """
        ]
    )
    parser = MimacomJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_mimacom_enforces_catalog_limit() -> None:
    page = listing_html(
        [
            listing_card(slug="sales-executive", title="Sales Executive"),
            listing_card(slug="java-engineer", title="Java Engineer"),
        ]
    )
    parser = MimacomJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_mimacom_wraps_listing_request_failures() -> None:
    parser = MimacomJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_mimacom_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["mimacom"]
    assert isinstance(parser, MimacomJobsParser)
    assert parser.base_url == settings.mimacom_jobs_base_url
    assert parser.max_jobs == settings.mimacom_jobs_max_jobs
    assert parser.detail_workers == settings.mimacom_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Mimacom", "filters": {}},
            "sources": ["mimacom", "mimacom"],
        }
    )
    assert request.sources == ["mimacom"]


def test_mimacom_jobs_render_as_direct_company_imports() -> None:
    parsed = MimacomJobsParser().normalize_job(
        {
            "id": "sales-executive",
            "title": "Sales Executive (m/f/d)",
            "location": "Zurich, Bern",
            "employment_type": "Full time",
            "url": "https://www.mimacom.com/jobs/sales-executive",
        }
    )

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="mimacom-sales-executive",
        added_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "mimacom-sales-executive"
    assert stored["logo"] == "company"
    assert stored["department"] == "Mimacom import"
    assert stored["company"] == "Mimacom"
