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
from app.services.parsers.companies.cudos import CudosJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://cudos.ch/de/jobs/"


def job_url(slug: str) -> str:
    return f"{BASE_URL}{slug}/"


def apply_url(value: str) -> str:
    return f"https://jobs.dualoo.com/link/{value}/apply?lang=DE"


def record(
    slug: str,
    *,
    title: str,
    workload: str,
    offices: list[str],
    posted_at: str | None = "2026-02-10",
) -> dict[str, object]:
    return {
        "id": slug,
        "title": title,
        "workload": workload,
        "offices": offices,
        "posted_at": posted_at,
    }


def official_records() -> list[dict[str, object]]:
    return [
        record(
            "junior-software-engineer-cudos-trail",
            title="Junior Software Engineer im Cross-Company-Programm",
            workload="100%",
            offices=["Zürich", "Chur"],
            posted_at=None,
        ),
        record(
            "senior-software-engineer-c-sharp",
            title="Senior Software Engineer C#",
            workload="80-100%",
            offices=["Chur", "Zürich"],
            posted_at="2025-12-22",
        ),
        record(
            "senior-software-engineer-c-oder-c-industrial-systems",
            title="Senior Software Engineer C# oder C++ - Industrial Systems",
            workload="80-100%",
            offices=["Zürich"],
            posted_at="2025-12-22",
        ),
    ]


def workload_label(value: str) -> str:
    return value.replace("-", "–").replace("%", " % (M/W/D)")


def organization_schema() -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Cudos",
            "url": "https://cudos.ch",
        }
    )


def listing_html(records: list[dict[str, object]], *, seo_records=None) -> str:
    cards = "".join(
        f"""
        <div class="css-grid__item">
          <a class="teaser" href="/de/jobs/{item["id"]}/">
            <div class="teaser__content">
              <span class="text--medium">{workload_label(str(item["workload"]))}</span>
              <h3 class="text--h4">{item["title"]}</h3>
            </div>
          </a>
        </div>
        """
        for item in records
    )
    seo_records = records if seo_records is None else seo_records
    seo = "".join(
        f"""
        <a href="/de/jobs/{item["id"]}/">
          <span class="button-label">{item["title"]}</span>
        </a>
        """
        for item in seo_records
    )
    return f"""
    <html><head>
      <link rel="canonical" href="{BASE_URL}">
      <script type="application/ld+json">{organization_schema()}</script>
    </head><body>
      <div class="app-content-plugin-32118">
        <div class="filter-container"
          data-ajax-filter-base-url="/de/jobs/1/?plugin_id=32118">
          <select id="category">
            <option value="">Alle</option>
            <option value="76">Standort Zürich</option>
            <option value="77">Standort Chur</option>
          </select>
        </div>
        {cards}
      </div>
      <div class="app-content-plugin-26416">{seo}</div>
    </body></html>
    """


def detail_html(
    item: dict[str, object],
    *,
    title: str | None = None,
    apply_host: str = "jobs.dualoo.com",
    include_jobposting: bool | None = None,
) -> str:
    include_jobposting = (
        item["posted_at"] is not None if include_jobposting is None else include_jobposting
    )
    applications: list[str] = []
    for index, office in enumerate(item["offices"]):
        application = apply_url(f"0000000{index}-0000-4000-8000-00000000000{index}")
        application = application.replace("jobs.dualoo.com", apply_host)
        applications.append(
            f'<a href="{application}"><span class="button-label">Bewerben für {office}</span></a>'
        )
    jobposting = ""
    if include_jobposting:
        locations = [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "Schweiz",
                    "addressLocality": "Fahrweid" if office == "Zürich" else office,
                },
            }
            for office in item["offices"]
        ]
        schema = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": item["title"],
            "datePosted": item["posted_at"],
            "employmentType": "FULL_TIME",
            "directApply": "TRUE",
            "hiringOrganization": {
                "@type": "Organization",
                "name": "Cudos Software Engineers",
            },
            "jobLocation": locations if len(locations) > 1 else locations[0],
        }
        jobposting = f'<script type="application/ld+json">{json.dumps(schema)}</script>'
    return f"""
    <html><head>
      <link rel="canonical" href="{job_url(str(item["id"]))}">
      <script type="application/ld+json">{organization_schema()}</script>
    </head><body>
      <main>
        <section class="hero">
          <div class="hero-content__background">
            <div class="text-container">
              <p class="text--h6">{workload_label(str(item["workload"]))}</p>
              <h1 class="text--h2">{title or item["title"]}</h1>
            </div>
          </div>
        </section>
        <section>
          <div class="content-plugin text-plugin text-container">
            <h2 class="text--h4">Das bewirkst du bei uns</h2>
            <ul><li>Du entwickelst innovative Software.</li></ul>
          </div>
          <div class="content-plugin text-plugin text-container">
            <h2 class="text--h4">Das bringst du mit</h2>
            <p>Du arbeitest gerne im Team.</p>
            <p>{jobposting}</p>
          </div>
          <div class="content-plugin text-plugin text-container">
            <h2 class="text--h4">Jetzt bewerben</h2>
            <p>Wir freuen uns auf deine Bewerbung.</p>
            {"".join(applications)}
          </div>
        </section>
      </main>
    </body></html>
    """


def test_cudos_scans_complete_catalog_and_enriches_details() -> None:
    records = official_records()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/de/jobs/":
            return httpx.Response(200, text=listing_html(records))
        slug = request.url.path.rstrip("/").split("/")[-1]
        item = next(value for value in records if value["id"] == slug)
        return httpx.Response(200, text=detail_html(item))

    result = CudosJobsParser(
        detail_workers=3,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 4
    assert result.message == ("Scanned 3 Cudos vacancies from the complete official catalog")
    assert len(result.jobs) == 3
    junior = result.jobs[0]
    assert junior.source == "cudos"
    assert junior.company == "Cudos AG"
    assert junior.location == ("8951 Fahrweid, Switzerland; 7000 Chur, Switzerland")
    assert junior.url == job_url("junior-software-engineer-cudos-trail")
    assert junior.apply_url == junior.url
    assert junior.posted_at is None
    assert junior.employment_type == "Full-time · 100%"
    assert junior.seniority == "Junior"
    assert junior.description and "Das bewirkst du bei uns" in junior.description
    assert junior.description and "- Du entwickelst innovative Software" in junior.description
    senior = result.jobs[1]
    assert senior.posted_at == "2025-12-22"
    assert senior.employment_type == "Full-time · 80-100%"
    assert senior.seniority == "Senior"
    assert senior.raw["detail"]["jobposting"]["schema"]["@type"] == "JobPosting"
    single_office = result.jobs[2]
    assert single_office.location == "8951 Fahrweid, Switzerland"
    assert single_office.apply_url and single_office.apply_url.startswith(
        "https://jobs.dualoo.com/link/"
    )


def test_cudos_preserves_listing_when_detail_fails() -> None:
    item = official_records()[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs/":
            return httpx.Response(200, text=listing_html([item]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        CudosJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Software Engineer C#"
    assert job.location == "Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_cudos_rejects_mismatched_detail_but_keeps_listing() -> None:
    item = official_records()[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs/":
            return httpx.Response(200, text=listing_html([item]))
        return httpx.Response(200, text=detail_html(item, title="Different vacancy"))

    job = (
        CudosJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_cudos_rejects_untrusted_external_apply_url() -> None:
    item = official_records()[2]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs/":
            return httpx.Response(200, text=listing_html([item]))
        return httpx.Response(
            200,
            text=detail_html(item, apply_host="example.com"),
        )

    job = (
        CudosJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == job.url
    assert "incomplete vacancy" in str(job.raw["detail_error"])


def test_cudos_rejects_catalog_cross_check_mismatch() -> None:
    records = official_records()
    parser = CudosJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(records, seo_records=records[:-1]),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="representations do not match"):
        parser.search(LinkedInSearchRequest())


def test_cudos_rejects_duplicate_ids() -> None:
    item = official_records()[0]
    parser = CudosJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([item, item]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_cudos_accepts_an_empty_official_catalog() -> None:
    parser = CudosJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html([])))
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == ("Scanned 0 Cudos vacancies from the complete official catalog")


def test_cudos_wraps_catalog_request_failures() -> None:
    parser = CudosJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_cudos_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["cudos"]
    assert isinstance(parser, CudosJobsParser)
    assert parser.base_url == settings.cudos_jobs_base_url
    assert parser.detail_workers == settings.cudos_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Cudos", "filters": {}},
            "sources": ["cudos", "cudos"],
        }
    )
    assert request.sources == ["cudos"]


def test_cudos_jobs_render_as_direct_company_imports() -> None:
    item = official_records()[1]
    job = CudosJobsParser().normalize_job(
        {
            "id": item["id"],
            "title": item["title"],
            "workload": item["workload"],
            "url": job_url(str(item["id"])),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"cudos-{item['id']}",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "cudos.ch"
    assert stored["logo"] == "company"
    assert stored["department"] == "Cudos import"
    assert stored["id"] == "cudos-senior-software-engineer-c-sharp"
