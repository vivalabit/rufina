from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.swatch_group import SwatchGroupJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def json(self) -> object:
        raise AssertionError("HTML response is not JSON")

    def css(self, selector: str, *args: object, **kwargs: object) -> object:
        return self.selector.css(selector, *args, **kwargs)


def listing_card(job_id: int, *, title: str) -> str:
    return f"""
    <div class="card h-100">
      <div class="card__img">
        <a href="/en/job/{job_id}">
          <img class="img--top" src="/brands/tissot.png" alt="IT">
        </a>
      </div>
      <div class="p2card__flush__body">
        <h4 class="card-title">
          <a class="text-text" href="/en/job/{job_id}">{title}</a>
        </h4>
        <p class="card__text">Build and support reliable IT services {job_id}.</p>
        <p><a href="/en/job/{job_id}">Read more</a></p>
      </div>
    </div>
    """


def listing_html(cards: list[str], *, next_path: str | None = None) -> str:
    pager = (
        f'<nav class="pager"><a rel="next" href="{next_path}">Next</a></nav>'
        if next_path
        else ""
    )
    return f"""
    <html><body>
      <form id="views-exposed-form-job-finder-page-1" action="/en/job-finder">
        <select name="jf_country"><option value="40" selected>Switzerland</option></select>
        <select name="domain"><option value="59" selected>IT</option></select>
      </form>
      <main>{''.join(cards)}{pager}</main>
    </body></html>
    """


def detail_html(job_id: int, *, title: str) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": "<p>Operate business-critical\nplatforms.</p>",
        "datePosted": "2026-08-07T09:00:58+02:00",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Tissot Ltd",
        },
    }
    schema_json = json.dumps(schema).replace("\\n", "\n")
    return f"""
    <html><body>
      <main>
        <h1 class="article__title--basic">{title}</h1>
        <div class="f-n-field-job-company-intro">
          <h2>The company</h2><p>Innovators by tradition.</p>
        </div>
        <div class="f-n-body">
          <h2>Job description</h2>
          <p>Operate business-critical platforms.</p>
          <ul><li>Automate services.</li><li>Support users.</li></ul>
        </div>
        <div class="f-n-field-job-profile">
          <h2>Profile</h2><p>Experience with Python and Microsoft 365.</p>
        </div>
        <aside class="job-card">
          <div id="jl"><p>Job location</p>Bälliz 12<br>2501 Biel/Bienne<br>Switzerland</div>
          <a class="btn" href="https://apply.example/jobs/{job_id}">
            Apply for this job
          </a>
        </aside>
        <script type="application/ld+json">{schema_json}</script>
      </main>
    </body></html>
    """


def test_swatch_group_scans_every_catalog_page_and_enriches_details() -> None:
    calls: list[str] = []

    def fetch_page(url: str) -> HtmlResponse:
        calls.append(url)
        parts = urlsplit(url)
        if parts.path == "/en/job-finder":
            page = parse_qs(parts.query).get("page", ["0"])[0]
            if page == "0":
                return HtmlResponse(
                    listing_html(
                        [listing_card(32458, title="IT Support Specialist")],
                        next_path=(
                            "/en/job-finder?jf_country=40&domain=59&position=All"
                            "&contract=All&time=All&page=1"
                        ),
                    )
                )
            return HtmlResponse(
                listing_html(
                    [listing_card(32759, title="IT-SYSTEM ENGINEER 100%, VOR ORT")]
                )
            )
        job_id = int(parts.path.rsplit("/", maxsplit=1)[-1])
        title = (
            "IT Support Specialist"
            if job_id == 32458
            else "IT-SYSTEM ENGINEER 100%, VOR ORT"
        )
        return HtmlResponse(detail_html(job_id, title=title))

    parser = SwatchGroupJobsParser(
        base_url=(
            "https://www.swatchgroup.test/en/job-finder?jf_country=40&domain=59"
            "&position=All&contract=All&time=All"
        ),
        detail_workers=2,
        fetch_page=fetch_page,
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Swatch Group Switzerland IT vacancies across 2 catalog page requests"
    )
    assert len(calls) == 4
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "swatch_group"
    assert first.title == "IT Support Specialist"
    assert first.company == "Tissot Ltd"
    assert first.location == "Bälliz 12 2501 Biel/Bienne Switzerland"
    assert first.url == "https://www.swatchgroup.test/en/job/32458"
    assert first.apply_url == "https://apply.example/jobs/32458"
    assert first.posted_at == "2026-08-07T09:00:58+02:00"
    assert first.employment_type is None
    assert first.description and "The company" in first.description
    assert first.description and "- Automate services." in first.description
    assert first.raw["listing_page"] == 1
    assert first.raw["brand_logo"] == (
        "https://www.swatchgroup.test/brands/tissot.png"
    )
    assert result.jobs[1].employment_type == "100%"


def test_swatch_group_preserves_listing_when_detail_request_fails() -> None:
    def fetch_page(url: str) -> HtmlResponse:
        if urlsplit(url).path == "/en/job-finder":
            return HtmlResponse(
                listing_html([listing_card(32458, title="IT Support Specialist")])
            )
        raise RuntimeError("detail temporarily unavailable")

    job = SwatchGroupJobsParser(fetch_page=fetch_page).search(
        LinkedInSearchRequest()
    ).jobs[0]

    assert job.title == "IT Support Specialist"
    assert job.company == "Swatch Group"
    assert job.location is None
    assert job.apply_url == job.url
    assert job.description == "Build and support reliable IT services 32458."
    assert "temporarily unavailable" in str(job.raw["detail_error"])


def test_swatch_group_rejects_malformed_listing_contract() -> None:
    parser = SwatchGroupJobsParser(
        fetch_page=lambda _: HtmlResponse("<html><body>Jobs</body></html>")
    )

    with pytest.raises(DirectCompanyRequestError, match="job finder form"):
        parser.search(LinkedInSearchRequest())


def test_swatch_group_enforces_catalog_page_limit() -> None:
    parser = SwatchGroupJobsParser(
        max_pages=1,
        fetch_page=lambda _: HtmlResponse(
            listing_html(
                [listing_card(32458, title="IT Support Specialist")],
                next_path="/en/job-finder?page=1",
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_swatch_group_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["swatch_group"]
    assert isinstance(parser, SwatchGroupJobsParser)
    assert parser.base_url == settings.swatch_group_jobs_base_url
    assert parser.max_pages == settings.swatch_group_jobs_max_pages
    assert parser.detail_workers == settings.swatch_group_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Swatch Group", "filters": {}},
            "sources": ["swatch_group", "swatch_group"],
        }
    )
    assert request.sources == ["swatch_group"]


def test_swatch_group_jobs_render_as_direct_company_imports() -> None:
    parser = SwatchGroupJobsParser()
    job = parser.normalize_job(
        {
            "id": "32458",
            "title": "IT Support Specialist",
            "url": "https://www.swatchgroup.com/en/job/32458",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="swatch_group-32458",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Swatch Group import"
    assert stored["id"] == "swatch_group-32458"
