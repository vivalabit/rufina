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
from app.services.parsers.companies.csem import CsemJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def posting(
    *,
    title: str,
    locality: str,
    date_posted: str,
    employment_type: str,
) -> dict[str, object]:
    return {
        "@type": "JobPosting",
        "title": title,
        "description": f"<p>Listing description for {title}.</p>",
        "hiringOrganization": {"@type": "Organization", "name": "CSEM"},
        "employmentType": employment_type,
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "CH",
                "addressLocality": locality,
            },
        },
        "datePosted": date_posted,
    }


def listing_html() -> str:
    postings = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "0": posting(
                    title="Senior Software Engineer (F/M/D) 100%",
                    locality="Neuchâtel",
                    date_posted="2026-08-01T00:00:00Z",
                    employment_type="FULL_TIME",
                ),
                "1": posting(
                    title="AI Research Intern (F/M/D)",
                    locality="Bern",
                    date_posted="2026-08-02T00:00:00Z",
                    employment_type="TEMPORARY",
                ),
            }
        ],
    }
    return f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(postings)}</script>
    </head><body><main>
      <p class="result-count">2 results</p>
      <a class="job-teaser" href="/en/jobs/191001">
        <div class="content">
          <p class="tax">Engineering</p>
          <h3>Senior Software Engineer (F/M/D) 100%</h3>
          <div class="intro-text"><p>Build reliable embedded platforms.</p></div>
          <div class="tags-wrapper">
            <div class="tag">Full Time</div><div class="tag">Permanent</div>
            <div class="tag">Neuchâtel</div>
          </div>
        </div>
      </a>
      <a class="job-teaser" href="/en/jobs/191002">
        <div class="content">
          <p class="tax">Internship</p>
          <h3>AI Research Intern (F/M/D)</h3>
          <div class="intro-text"><p>Research efficient vision models.</p></div>
          <div class="tags-wrapper">
            <div class="tag">Full Time</div><div class="tag">Temporary</div>
            <div class="tag">Bern</div>
          </div>
        </div>
      </a>
    </main></body></html>
    """


def detail_html(
    *,
    job_id: str,
    title: str,
    workload: str,
    contract_type: str,
    locality: str,
) -> str:
    return f"""
    <html><head>
      <link rel="canonical" href="https://www.csem.test/en/jobs/{job_id}/">
    </head><body><main class="job-page">
      <div class="container wrapper">
        <h5 class="title-label">Engineering</h5>
        <div class="head-container"><h1>{title}</h1></div>
        <div class="info-group">
          <div class="info-item"><span>{workload}</span></div>
          <div class="info-item"><span>{contract_type}</span></div>
          <div class="info-item"><span>{locality}</span></div>
        </div>
        <a href="https://apps.csem.ch/jobs/register.aspx?jobId={job_id}">
          Apply for this job
        </a>
        <div class="job-content">
          <p>Help us build more impactful technology.</p>
          <h2>Your Mission</h2>
          <p>Develop reliable systems.</p>
          <ul><li>Own production services.</li><li>Support research teams.</li></ul>
        </div>
      </div>
    </main></body></html>
    """


def test_csem_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=listing_html())
        job_id = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        if job_id == "191001":
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=job_id,
                    title="Senior Software Engineer (F/M/D) 100%",
                    workload="100%",
                    contract_type="Permanent",
                    locality="Neuchâtel",
                ),
            )
        if job_id == "191002":
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=job_id,
                    title="AI Research Intern (F/M/D)",
                    workload="80%",
                    contract_type="Temporary",
                    locality="Bern",
                ),
            )
        return httpx.Response(404)

    parser = CsemJobsParser(
        base_url="https://www.csem.test/en/jobs/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 2 CSEM vacancies from one page"
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "csem"
    assert first.title == "Senior Software Engineer (F/M/D) 100%"
    assert first.company == "CSEM"
    assert first.location == "Neuchâtel"
    assert first.url == "https://www.csem.test/en/jobs/191001/"
    assert first.apply_url == "https://apps.csem.ch/jobs/register.aspx?jobId=191001"
    assert first.posted_at == "2026-08-01T00:00:00Z"
    assert first.employment_type == "Full Time, Permanent, 100%"
    assert first.description == (
        "Help us build more impactful technology.\n\n"
        "Your Mission\n\n"
        "Develop reliable systems.\n\n"
        "Own production services.\n"
        "Support research teams."
    )
    assert first.raw["id"] == "191001"
    assert first.raw["category"] == "Engineering"
    assert isinstance(first.raw["detail"], dict)


def test_csem_preserves_listing_when_detail_request_fails() -> None:
    one_job_listing = (
        listing_html()
        .replace(
            '<p class="result-count">2 results</p>',
            '<p class="result-count">1 result</p>',
        )
        .replace(
            '<a class="job-teaser" href="/en/jobs/191002">',
            '<a class="ignored" href="/en/jobs/191002">',
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=one_job_listing)
        return httpx.Response(503, text="temporarily unavailable")

    parser = CsemJobsParser(
        base_url="https://www.csem.test/en/jobs/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    job = result.jobs[0]
    assert job.description == ("Listing description for Senior Software Engineer (F/M/D) 100%.")
    assert job.url == "https://www.csem.test/en/jobs/191001"
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_csem_rejects_listing_without_catalog_contract() -> None:
    parser = CsemJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="result count"):
        parser.search(LinkedInSearchRequest())


def test_csem_rejects_incomplete_catalog() -> None:
    incomplete = listing_html().replace(
        '<a class="job-teaser" href="/en/jobs/191002">',
        '<a class="ignored" href="/en/jobs/191002">',
    )
    parser = CsemJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=incomplete))
    )

    with pytest.raises(DirectCompanyRequestError, match="declared 2 results"):
        parser.search(LinkedInSearchRequest())


def test_csem_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["csem"]
    assert isinstance(parser, CsemJobsParser)
    assert parser.base_url == settings.csem_jobs_base_url
    assert parser.detail_workers == settings.csem_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "CSEM", "filters": {}},
            "sources": ["csem", "csem"],
        }
    )
    assert request.sources == ["csem"]


def test_csem_jobs_render_as_direct_company_imports() -> None:
    parser = CsemJobsParser()
    job = parser.normalize_job(
        {
            "id": "191001",
            "title": "Senior Software Engineer (F/M/D) 100%",
            "category": "Engineering",
            "teaser": "Build reliable systems.",
            "schedule": "Full Time",
            "contract_type": "Permanent",
            "location": "Neuchâtel",
            "url": "https://www.csem.ch/en/jobs/191001",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="csem-191001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "CSEM import"
    assert stored["id"] == "csem-191001"
