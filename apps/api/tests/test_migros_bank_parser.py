from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.migros_bank import MigrosBankJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

LISTING_HTML = """
<html><body><ul>
  <li class="search-layout-list-item">
    <a href="/de/unsere-unternehmen/job/migros-bank/devsecops-engineer-alle/job-1">
      <p>Migros Bank</p>
      <h3>
        <span class="font-bold">DevSecOps Engineer (alle)</span>
        <span class="font-bold"> ‧ </span><span>80 – 100%</span>
      </h3>
      <ul class="dot-list">
        <li>8304 Wallisellen</li><li>Festanstellung (unbefristet)</li>
        <li>Homeoffice-Möglichkeit</li>
      </ul>
    </a>
  </li>
  <li class="search-layout-list-item">
    <a href="/de/unsere-unternehmen/job/migros-bank/business-engineer-alle/job-2">
      <p>Migros Bank</p>
      <h3>
        <span class="font-bold">Business Engineer (alle)</span>
        <span class="font-bold"> ‧ </span><span>60 – 100%</span>
      </h3>
      <ul class="dot-list">
        <li>8001 Zürich</li><li>Festanstellung (unbefristet)</li>
      </ul>
    </a>
  </li>
  <li class="search-layout-list-item">
    <a href="/de/unsere-unternehmen/job/galaxus/ignored/job-3">
      <p>Galaxus</p><h3><span class="font-bold">Ignored</span></h3>
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
        "description": "Build secure digital banking solutions.",
        "identifier": {"@type": "PropertyValue", "value": job_id},
        "datePosted": "2026-08-05T13:21:49+0200",
        "hiringOrganization": {"@type": "Organization", "name": "Migros Bank"},
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
        <p>Harden the delivery platform</p><p>Improve banking services</p>
      </section>
      <section id="skills"><h3>Was du mitbringst</h3>
        <h4>Experience with cloud security</h4><p>Fluent German</p>
      </section>
      <a href="https://career2.successfactors.eu/careers?career_ns=job_application&amp;company=MigrosP1&amp;career_job_req_id={job_id}&amp;lang=de_DE">Jetzt bewerben</a>
    </main></body></html>
    """


def test_migros_bank_parser_scans_page_and_enriches_every_job() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/offene-stellen"):
            return httpx.Response(200, text=LISTING_HTML)
        if request.url.path.endswith("/job-1"):
            return httpx.Response(
                200,
                text=detail_html(
                    title="DevSecOps Engineer (alle)",
                    job_id="job-1",
                    locality="Wallisellen",
                    postal_code="8304",
                ),
            )
        if request.url.path.endswith("/job-2"):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Business Engineer (alle)",
                    job_id="job-2",
                    locality="Zürich",
                    postal_code="8001",
                ),
            )
        return httpx.Response(404)

    parser = MigrosBankJobsParser(
        base_url="https://jobs.example.test/de/migros-bank/offene-stellen",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 2 Migros Bank vacancies from one page"
    assert len(result.jobs) == 2
    assert requests[0] == "GET /de/migros-bank/offene-stellen"
    assert len(requests) == 3
    first = result.jobs[0]
    assert first.source == "migros_bank"
    assert first.title == "DevSecOps Engineer (alle)"
    assert first.company == "Migros Bank"
    assert first.location == "8304 Wallisellen"
    assert first.posted_at == "2026-08-05T13:21:49+0200"
    assert first.employment_type == (
        "Festanstellung (unbefristet), 80% - 100%, Homeoffice-Möglichkeit"
    )
    assert first.apply_url is not None
    assert "career_ns=job_application" in first.apply_url
    assert "career_job_req_id=job-1" in first.apply_url
    assert first.description == (
        "Build secure digital banking solutions.\n\n"
        "Was du bewegst\nHarden the delivery platform\nImprove banking services\n\n"
        "Was du mitbringst\nExperience with cloud security\nFluent German"
    )


def test_migros_bank_parser_keeps_listing_when_detail_request_fails() -> None:
    single_listing = LISTING_HTML.replace(
        '<li class="search-layout-list-item">\n    <a href="/de/unsere-unternehmen/job/migros-bank/business-engineer-alle/job-2">',
        '<li class="ignored">\n    <a href="/de/unsere-unternehmen/job/migros-bank/business-engineer-alle/job-2">',
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/offene-stellen"):
            return httpx.Response(200, text=single_listing)
        return httpx.Response(503)

    parser = MigrosBankJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].title == "DevSecOps Engineer (alle)"
    assert result.jobs[0].location == "8304 Wallisellen"
    assert result.jobs[0].raw["detail_error"]


def test_migros_bank_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["migros_bank"]
    assert isinstance(parser, MigrosBankJobsParser)
    assert parser.base_url == settings.migros_bank_jobs_base_url
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Migros Bank", "filters": {}},
            "sources": ["migros_bank", "migros_bank"],
        }
    )
    assert request.sources == ["migros_bank"]


def test_migros_bank_jobs_render_as_direct_company_imports() -> None:
    parser = MigrosBankJobsParser()
    job = parser.normalize_job(
        {
            "id": "job-1",
            "title": "DevSecOps Engineer (alle)",
            "company": "Migros Bank",
            "location": "8304 Wallisellen",
            "employment_type": "Festanstellung (unbefristet)",
            "workload": "80 – 100%",
            "workplace_models": ["Homeoffice-Möglichkeit"],
            "url": "https://jobs.migros.ch/de/job/migros-bank/job-1",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="migros_bank-job-1",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Migros Bank import"
    assert stored["id"] == "migros_bank-job-1"
