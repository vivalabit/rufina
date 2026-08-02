from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.galaxus import GalaxusJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

LISTING_HTML = """
<html><body><ul>
  <li class="search-layout-list-item">
    <a href="/de/unsere-unternehmen/job/galaxus/junior-engineer/job-1">
      <p>Galaxus</p>
      <h3>
        <span class="font-bold">Junior Software Engineer (w/m/d)</span>
        <span class="font-bold"> ‧ </span><span>80 – 100%</span>
      </h3>
      <ul class="dot-list">
        <li>8005 Zürich</li><li>Festanstellung (unbefristet)</li>
        <li>Homeoffice-Möglichkeit</li>
      </ul>
    </a>
  </li>
  <li class="search-layout-list-item">
    <a href="/en/our-companies/job/galaxus/data-architect/job-2">
      <p>Galaxus</p>
      <h3>
        <span class="font-bold">Data Architect (f/m/d)</span>
        <span class="font-bold"> ‧ </span><span>60 – 100%</span>
      </h3>
      <ul class="dot-list">
        <li>5606 Dintikon</li><li>Permanent employment</li>
      </ul>
    </a>
  </li>
</ul></body></html>
"""


def detail_html(
    *,
    title: str,
    job_id: str,
    locality: str,
    postal_code: str,
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": "Build reliable customer-facing platforms.",
        "identifier": {"@type": "PropertyValue", "value": job_id},
        "datePosted": "2026-07-30T15:38:33+0200",
        "hiringOrganization": {"@type": "Organization", "name": "Galaxus"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": locality,
                "postalCode": postal_code,
                "addressCountry": "CH",
            },
        },
        "employmentType": "Festanstellung (unbefristet)",
        "workHours": "80% - 100%",
    }
    return f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body><main class="job-ad-wrapper">
      <section id="tasks"><h3>Was du bewegst</h3>
        <p>Develop distributed systems</p><p>Improve customer experience</p>
      </section>
      <section id="skills"><h3>Was du mitbringst</h3>
        <h4>First software-development experience</h4>
        <p>Knowledge of C# and .NET</p><p>Fluent German and English</p>
      </section>
      <a href="https://www.galaxus.ch/de/joboffer/apply/{job_id}">Jetzt bewerben</a>
    </main></body></html>
    """


def test_galaxus_parser_scans_single_page_and_enriches_every_job() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/offene-stellen"):
            return httpx.Response(200, text=LISTING_HTML)
        if request.url.path.endswith("/job-1"):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Junior Software Engineer (w/m/d)",
                    job_id="job-1",
                    locality="Zürich",
                    postal_code="8005",
                ),
            )
        if request.url.path.endswith("/job-2"):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Data Architect (f/m/d)",
                    job_id="job-2",
                    locality="Dintikon",
                    postal_code="5606",
                ),
            )
        return httpx.Response(404)

    parser = GalaxusJobsParser(
        base_url="https://jobs.example.test/de/galaxus/offene-stellen",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 2 Galaxus vacancies from one page"
    assert len(result.jobs) == 2
    assert requests[0] == "GET /de/galaxus/offene-stellen"
    assert len(requests) == 3
    first = result.jobs[0]
    assert first.source == "galaxus"
    assert first.title == "Junior Software Engineer (w/m/d)"
    assert first.company == "Galaxus"
    assert first.location == "8005 Zürich"
    assert first.posted_at == "2026-07-30T15:38:33+0200"
    assert first.employment_type == (
        "Festanstellung (unbefristet), 80% - 100%, Homeoffice-Möglichkeit"
    )
    assert first.apply_url == "https://www.galaxus.ch/de/joboffer/apply/job-1"
    assert first.description == (
        "Build reliable customer-facing platforms.\n\n"
        "Was du bewegst\nDevelop distributed systems\nImprove customer experience\n\n"
        "Was du mitbringst\nFirst software-development experience\n"
        "Knowledge of C# and .NET\nFluent German and English"
    )


def test_galaxus_parser_keeps_listing_when_detail_request_fails() -> None:
    single_listing = LISTING_HTML.replace(
        '<li class="search-layout-list-item">\n    <a href="/en/our-companies/job/galaxus/data-architect/job-2">',
        '<li class="ignored">\n    <a href="/en/our-companies/job/galaxus/data-architect/job-2">',
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/offene-stellen"):
            return httpx.Response(200, text=single_listing)
        return httpx.Response(503)

    parser = GalaxusJobsParser(
        base_url="https://jobs.example.test/de/galaxus/offene-stellen",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Junior Software Engineer (w/m/d)"
    assert result.jobs[0].location == "8005 Zürich"
    assert result.jobs[0].raw["detail_error"]


def test_galaxus_is_registered_as_a_direct_company_source() -> None:
    runner = create_vacancy_search_runner(Settings())

    assert isinstance(runner.parsers["galaxus"], GalaxusJobsParser)
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Galaxus", "filters": {}},
            "sources": ["galaxus", "galaxus"],
        }
    )
    assert request.sources == ["galaxus"]


def test_galaxus_jobs_render_as_direct_company_imports() -> None:
    parser = GalaxusJobsParser()
    job = parser.normalize_job(
        {
            "id": "job-1",
            "title": "Junior Software Engineer (w/m/d)",
            "company": "Galaxus",
            "location": "8005 Zürich",
            "employment_type": "Festanstellung (unbefristet)",
            "workload": "80 – 100%",
            "workplace_models": ["Homeoffice-Möglichkeit"],
            "url": "https://jobs.migros.ch/de/job/galaxus/job-1",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="galaxus-job-1",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Galaxus import"
