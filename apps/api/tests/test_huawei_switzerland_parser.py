from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.huawei_switzerland import (
    HuaweiSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_html(*, declared_count: int = 2, include_second: bool = True) -> str:
    second = (
        """
      <li>
        <a href="https://careers.huawei.test/jobs/1002-ai-research-intern">
          <span></span>AI Research Intern
        </a>
        <span class="text-base">
          <span>Computing Systems</span><span>Lausanne</span>
        </span>
      </li>
    """
        if include_second
        else ""
    )
    return f"""
    <html><body>
      <div class="jobs-list-container">
        <p><span>{declared_count} jobs</span></p>
        <ul id="jobs_list_container">
          <li>
            <a href="/jobs/1001-senior-software-engineer">
              <span></span>Senior Software Engineer
            </a>
            <span class="text-base">
              <span>Advance Computing &amp; Storage</span><span>Zürich</span>
            </span>
          </li>
          {second}
        </ul>
      </div>
    </body></html>
    """


def detail_html(
    *,
    job_id: str,
    title: str,
    location: str,
    department: str,
    employment_type: str,
    seniority: str,
) -> str:
    public_url = f"https://careers.huawei.test/jobs/{job_id}-{title.lower().replace(' ', '-')}"
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "&lt;p&gt;Build advanced computing platforms.&lt;/p&gt;"
            "&lt;h2&gt;Responsibilities&lt;/h2&gt;"
            "&lt;ul&gt;&lt;li&gt;Research reliable systems.&lt;/li&gt;&lt;/ul&gt;"
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": "Huawei Switzerland",
            "value": job_id,
        },
        "datePosted": "2026-08-01T10:03:20+02:00",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Huawei Switzerland",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
                "addressCountry": "CH",
            },
        },
    }
    return f"""
    <html><head>
      <meta property="og:url" content="{public_url}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <main
        data-careersite--jobs--form-overlay-job-application-url-value="
          {public_url}/applications/new
        "
      >
        <section><dl>
          <dt>Department</dt><dd>{department}</dd>
          <dt>Locations</dt><dd>{location}</dd>
          <dt>Employment type</dt><dd>{employment_type}</dd>
          <dt>Employment level</dt><dd>{seniority}</dd>
        </dl></section>
      </main>
    </body></html>
    """


def test_huawei_switzerland_scans_and_enriches_full_catalog() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html())
        job_id = request.url.path.split("/", maxsplit=3)[2].split("-", maxsplit=1)[0]
        if job_id == "1001":
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=job_id,
                    title="Senior Software Engineer",
                    location="Zürich",
                    department="Advance Computing & Storage",
                    employment_type="Full-time",
                    seniority="Professionals",
                ),
            )
        if job_id == "1002":
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=job_id,
                    title="AI Research Intern",
                    location="Lausanne",
                    department="Computing Systems",
                    employment_type="Internship",
                    seniority="Students",
                ),
            )
        return httpx.Response(404)

    parser = HuaweiSwitzerlandJobsParser(
        base_url="https://careers.huawei.test/jobs",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 Huawei Switzerland vacancies from one page")
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "huawei_switzerland"
    assert first.title == "Senior Software Engineer"
    assert first.company == "Huawei Switzerland"
    assert first.location == "Zürich"
    assert first.url == ("https://careers.huawei.test/jobs/1001-senior-software-engineer")
    assert first.apply_url == f"{first.url}/applications/new"
    assert first.posted_at == "2026-08-01T10:03:20+02:00"
    assert first.employment_type == "Full-time"
    assert first.seniority == "Professionals"
    assert first.description == (
        "Build advanced computing platforms.\nResponsibilities\nResearch reliable systems."
    )
    assert first.raw["id"] == "1001"
    assert first.raw["department"] == "Advance Computing & Storage"
    assert isinstance(first.raw["detail"]["schema"], dict)


def test_huawei_switzerland_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(
                200,
                text=listing_html(declared_count=1, include_second=False),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = HuaweiSwitzerlandJobsParser(
        base_url="https://careers.huawei.test/jobs",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    job = result.jobs[0]
    assert job.title == "Senior Software Engineer"
    assert job.location == "Zürich"
    assert job.url == "https://careers.huawei.test/jobs/1001-senior-software-engineer"
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_huawei_switzerland_rejects_listing_without_catalog_contract() -> None:
    parser = HuaweiSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        parser.search(LinkedInSearchRequest())


def test_huawei_switzerland_rejects_incomplete_catalog() -> None:
    parser = HuaweiSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(declared_count=2, include_second=False),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="declared 2 jobs"):
        parser.search(LinkedInSearchRequest())


def test_huawei_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["huawei_switzerland"]
    assert isinstance(parser, HuaweiSwitzerlandJobsParser)
    assert parser.base_url == settings.huawei_switzerland_jobs_base_url
    assert parser.detail_workers == settings.huawei_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Huawei Switzerland", "filters": {}},
            "sources": ["huawei_switzerland", "huawei_switzerland"],
        }
    )
    assert request.sources == ["huawei_switzerland"]


def test_huawei_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = HuaweiSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "1001",
            "title": "Senior Software Engineer",
            "department": "Advance Computing & Storage",
            "location": "Zürich",
            "url": ("https://careers.huaweirc.ch/jobs/1001-senior-software-engineer"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="huawei_switzerland-1001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Huawei Switzerland import"
    assert stored["id"] == "huawei_switzerland-1001"


def test_huawei_reads_heading_counter_and_still_detects_missing_cards() -> None:
    from app.services.parsers.companies.huawei_switzerland import parse_listing_html

    page = listing_html().replace("<p><span>2 jobs</span></p>", "<h2>2 jobs<span></span></h2>")
    assert len(parse_listing_html(page, page_url="https://careers.huawei.test/jobs")) == 2
    with pytest.raises(DirectCompanyRequestError):
        parse_listing_html(
            page.replace("<h2>2 jobs", "<h2>3 jobs"), page_url="https://careers.huawei.test/jobs"
        )
