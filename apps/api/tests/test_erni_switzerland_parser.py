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
from app.services.parsers.companies.erni_switzerland import ErniSwitzerlandJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.betterask.erni/ch-en/job-opportunities/"


def job_record(
    job_id: str,
    title: str,
    location: str,
    department: str | None,
) -> dict[str, str | None]:
    return {
        "id": job_id,
        "title": title,
        "location": location,
        "department": department,
        "work_model": "Hybrid Remote",
    }


def official_records() -> list[dict[str, str | None]]:
    return [
        job_record("8175060", "Senior Accountant (a)", "Zürich", None),
        job_record(
            "8174933",
            "Key Account & Business Development Manager Mobility (80–100%)",
            "Bern",
            "Sales",
        ),
        job_record(
            "7852745",
            "Rust Software Engineer (a)",
            "Zürich, Bern, Basel",
            "Software Engineering",
        ),
    ]


def summary(item: dict[str, str | None]) -> str:
    values = [item["location"], item["department"], item["work_model"]]
    return " · ".join(str(value) for value in values if value)


def job_url(item: dict[str, str | None]) -> str:
    return f"https://www.betterask.erni/ch-en/switzerland-jobs/{item['id']}/"


def listing_html(records: list[dict[str, str | None]]) -> str:
    cards = "".join(
        f"""
        <div class="offer-wrapper"
          data-search="{item["title"]} - {summary(item)}"
          data-id-job="{item["id"]}">
          <div class="details">
            <div class="title">{item["title"]}</div>
            <p>{summary(item)}</p>
          </div>
          <a class="offer-btn" href="{job_url(item)} ">More information</a>
        </div>
        """
        for item in records
    )
    return f"""
    <html><head><link rel="canonical" href="{BASE_URL}"></head><body>
      <div id="shortcut-wrapper"><div class="offer-list-wrapper">{cards}</div></div>
    </body></html>
    """


def teamtailor_html(records: list[dict[str, str | None]]) -> str:
    links = "".join(
        f'<a href="https://weareerniswjobs.teamtailor.com/jobs/{item["id"]}-job-title">'
        f"{item['title']}</a>"
        for item in records
    )
    return f"<html><body>{links}</body></html>"


def detail_html(
    item: dict[str, str | None],
    *,
    schema_location: str | None = None,
    apply_host: str = "weareerniswjobs.teamtailor.com",
) -> str:
    location = schema_location or str(item["location"])
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "hiringOrganization": {"@type": "Organization", "name": "ERNI"},
        "datePosted": "2026-06-04T13:45:20.835+02:00",
        "description": "ERNI opportunity",
        "employmentType": item["work_model"],
        "industry": item["department"],
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
            },
        },
        "title": item["title"],
    }
    return f"""
    <html><head>
      <link rel="canonical" href="{job_url(item)}">
    </head><body>
      <header class="page-header">
        <div class="col-xl-6">
          <h1 class="entry-title"><b>{item["title"]}</b></h1>
          <p><b>{summary(item)}</b></p>
        </div>
      </header>
      <div class="page-content">
        <div class="col-lg-6 text">
          <p><strong>Wir sind ERNI.</strong> Gemeinsam gestalten wir die Zukunft.</p>
          <h2>Was Dich erwartet:</h2>
          <ul><li>Entwicklung moderner Softwarelösungen</li></ul>
        </div>
      </div>
      <div id="modalJob">
        <iframe src="https://{apply_host}/jobs/{item["id"]}-job-title/applications/new?iframe=true"></iframe>
      </div>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_erni_scans_complete_catalog_and_enriches_details() -> None:
    records = official_records()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "weareerniswjobs.teamtailor.com":
            return httpx.Response(200, text=teamtailor_html(records))
        if request.url.path == "/ch-en/job-opportunities/":
            return httpx.Response(200, text=listing_html(records))
        item = next(value for value in records if value["id"] in request.url.path)
        return httpx.Response(200, text=detail_html(item))

    result = ErniSwitzerlandJobsParser(
        detail_workers=3,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 5
    assert result.message == (
        "Scanned 3 ERNI Switzerland vacancies from the complete official catalog "
        "cross-checked against Teamtailor"
    )
    assert len(result.jobs) == 3
    job = result.jobs[2]
    assert job.source == "erni_switzerland"
    assert job.title == "Rust Software Engineer (a)"
    assert job.company == "ERNI Schweiz AG"
    assert job.location == "Zürich, Bern, Basel"
    assert job.url == job_url(records[2])
    assert job.apply_url == (
        "https://weareerniswjobs.teamtailor.com/jobs/7852745-job-title/applications/new"
    )
    assert job.posted_at == "2026-06-04"
    assert job.employment_type == "Hybrid Remote"
    assert job.description and "Was Dich erwartet" in job.description
    assert job.description and "- Entwicklung moderner Softwarelösungen" in job.description
    assert job.raw["detail"]["department"] == "Software Engineering"


def test_erni_preserves_listing_when_detail_fails() -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "weareerniswjobs.teamtailor.com":
            return httpx.Response(200, text=teamtailor_html([item]))
        if request.url.path == "/ch-en/job-opportunities/":
            return httpx.Response(200, text=listing_html([item]))
        return httpx.Response(503)

    job = (
        ErniSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Accountant (a)"
    assert job.location == "Zürich"
    assert job.apply_url == job.url
    assert job.posted_at is None
    assert job.employment_type == "Hybrid Remote"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_erni_rejects_teamtailor_catalog_mismatch() -> None:
    records = official_records()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "weareerniswjobs.teamtailor.com":
            return httpx.Response(200, text=teamtailor_html(records[:-1]))
        return httpx.Response(200, text=listing_html(records))

    parser = ErniSwitzerlandJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="does not match Teamtailor"):
        parser.search(LinkedInSearchRequest())


def test_erni_rejects_duplicate_listing_ids() -> None:
    item = official_records()[0]
    parser = ErniSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([item, item]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("schema_location", "apply_host", "error"),
    [
        ("Berlin", "weareerniswjobs.teamtailor.com", "non-Swiss"),
        ("Zürich", "evil.example", "incomplete vacancy"),
    ],
)
def test_erni_keeps_listing_when_detail_is_untrusted(
    schema_location: str,
    apply_host: str,
    error: str,
) -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "weareerniswjobs.teamtailor.com":
            return httpx.Response(200, text=teamtailor_html([item]))
        if request.url.path == "/ch-en/job-opportunities/":
            return httpx.Response(200, text=listing_html([item]))
        return httpx.Response(
            200,
            text=detail_html(
                item,
                schema_location=schema_location,
                apply_host=apply_host,
            ),
        )

    job = (
        ErniSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == job.url
    assert job.description is None
    assert error in str(job.raw["detail_error"])


def test_erni_accepts_an_empty_official_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "weareerniswjobs.teamtailor.com":
            return httpx.Response(200, text=teamtailor_html([]))
        return httpx.Response(200, text=listing_html([]))

    result = ErniSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert result.jobs == []
    assert "Scanned 0 ERNI Switzerland vacancies" in result.message


def test_erni_wraps_catalog_request_failures() -> None:
    parser = ErniSwitzerlandJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_erni_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["erni_switzerland"]
    assert isinstance(parser, ErniSwitzerlandJobsParser)
    assert parser.base_url == settings.erni_switzerland_jobs_base_url
    assert parser.catalog_url == settings.erni_switzerland_jobs_catalog_url
    assert parser.detail_workers == settings.erni_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ERNI Switzerland", "filters": {}},
            "sources": ["erni_switzerland", "erni_switzerland"],
        }
    )
    assert request.sources == ["erni_switzerland"]


def test_erni_jobs_render_as_direct_company_imports() -> None:
    item = official_records()[2]
    job = ErniSwitzerlandJobsParser().normalize_job(
        {
            **item,
            "url": job_url(item),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="erni_switzerland-7852745",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "www.betterask.erni"
    assert stored["logo"] == "company"
    assert stored["department"] == "ERNI Switzerland import"
    assert stored["id"] == "erni_switzerland-7852745"
