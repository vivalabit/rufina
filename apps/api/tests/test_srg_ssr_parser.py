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
from app.services.parsers.companies.srg_ssr import SrgSsrJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

JOB_ONE_ID = "ba2e34a8-f6d3-4190-9557-30f463c1420d"
JOB_TWO_ID = "49ebb65c-5a8e-4eb1-a9af-4be275b513b9"


def listing_card(*, job_id: str, slug: str, title: str, summary: str) -> str:
    return f"""
    <div class="section group jobContent countJobRecords">
      <div class="col span_7_of_12 item">
        <a href="https://jobs.srgssr.test/srg/job-vacancies/{slug}/{job_id}">
          <h1>\u200b{title}\u200b</h1>
        </a>
        <small>{summary}</small>
        <p>Help shape the Swiss public media service.</p>
      </div>
    </div>
    """


def listing_html() -> str:
    cards = "".join(
        [
            listing_card(
                job_id=JOB_ONE_ID,
                slug="prozessanalyst-in",
                title="Prozessanalyst:in",
                summary="100% in Nach Vereinbarung",
            ),
            listing_card(
                job_id=JOB_TWO_ID,
                slug="assistent-in-stab",
                title="Assistent:in Stab",
                summary="80-100%, Bern",
            ),
        ]
    )
    return f"""
    <html><body>
      <form id="oh-form"></form>
      <section id="jobResults">{cards}</section>
    </body></html>
    """


def detail_html(*, job_id: str, title: str, city: str) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": f"\u200b{title}\u200b",
        "description": (
            "<p><div>Das ist Ihr Beitrag</div><br>"
            "<ul><li>Analyse and improve processes.</li>"
            "<li>Support the service public.</li></ul></p>"
        ),
        "datePosted": "2026-07-20",
        "validThrough": "2026-08-23",
        "employmentType": "FULL_TIME",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "Switzerland",
                "addressLocality": city,
            },
        },
    }
    return f"""
    <html><body>
      <a id="apply-button"
         href="//jobs.srgssr.test/public/v1/redirect/{job_id}/ats/">
        Jetzt bewerben
      </a>
    </body></html>
    <script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_srg_ssr_scans_and_enriches_full_catalog() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.host == "ohws.prospective.test":
            assert request.url.params["filter_10"] == "1124107"
            assert request.url.params["lang"] == "en"
            return httpx.Response(200, text=listing_html())
        job_id = request.url.path.rstrip("/").split("/")[-1]
        title = "Prozessanalyst:in" if job_id == JOB_ONE_ID else "Assistent:in Stab"
        city = "Bern" if job_id == JOB_ONE_ID else "Zürich"
        return httpx.Response(
            200,
            text=detail_html(job_id=job_id, title=title, city=city),
        )

    parser = SrgSsrJobsParser(
        base_url="https://www.srgssr.test/en/jobs-career/jobs",
        catalog_url=(
            "https://ohws.prospective.test/public/v1/careercenter/1000936/"
            "?sub=1&srg=1&filter_10=1124107&lang=en"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.search_url == "https://www.srgssr.test/en/jobs-career/jobs"
    assert result.message == ("Scanned 2 SRG SSR vacancies from the Prospective catalog")
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "srg_ssr"
    assert first.title == "Prozessanalyst:in"
    assert first.company == "SRG SSR"
    assert first.location == "Bern"
    assert first.url and first.url.endswith(JOB_ONE_ID)
    assert first.apply_url == (f"https://jobs.srgssr.test/public/v1/redirect/{JOB_ONE_ID}/ats/")
    assert first.posted_at == "2026-07-20"
    assert first.employment_type == "100%"
    assert first.description == (
        "Das ist Ihr Beitrag\n\n- Analyse and improve processes.\n- Support the service public."
    )
    assert first.raw["id"] == JOB_ONE_ID
    assert first.raw["detail"]["valid_through"] == "2026-08-23"


def test_srg_ssr_preserves_listing_when_detail_fails() -> None:
    one_card = listing_html().replace(
        listing_card(
            job_id=JOB_TWO_ID,
            slug="assistent-in-stab",
            title="Assistent:in Stab",
            summary="80-100%, Bern",
        ),
        "",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ohws.prospective.test":
            return httpx.Response(200, text=one_card)
        return httpx.Response(503, text="temporarily unavailable")

    parser = SrgSsrJobsParser(
        catalog_url=(
            "https://ohws.prospective.test/public/v1/careercenter/1000936/"
            "?filter_10=1124107&lang=en"
        ),
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Prozessanalyst:in"
    assert job.location == "Nach Vereinbarung"
    assert job.posted_at is None
    assert job.description == "Help shape the Swiss public media service."
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_srg_ssr_rejects_listing_without_catalog_contract() -> None:
    parser = SrgSsrJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Vacancies</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="catalog contract"):
        parser.search(LinkedInSearchRequest())


def test_srg_ssr_rejects_duplicate_vacancy_ids() -> None:
    duplicate = listing_html().replace(JOB_TWO_ID, JOB_ONE_ID)
    parser = SrgSsrJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=duplicate))
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_srg_ssr_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["srg_ssr"]
    assert isinstance(parser, SrgSsrJobsParser)
    assert parser.base_url == settings.srg_ssr_jobs_base_url
    assert parser.catalog_url == settings.srg_ssr_jobs_catalog_url
    assert parser.detail_workers == settings.srg_ssr_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SRG SSR", "filters": {}},
            "sources": ["srg_ssr", "srg_ssr"],
        }
    )
    assert request.sources == ["srg_ssr"]


def test_srg_ssr_jobs_render_as_direct_company_imports() -> None:
    parser = SrgSsrJobsParser()
    job = parser.normalize_job(
        {
            "id": JOB_ONE_ID,
            "title": "Prozessanalyst:in",
            "location": "Bern",
            "workload": "100%",
            "url": (f"https://jobs.srgssr.ch/srg/job-vacancies/prozessanalyst-in/{JOB_ONE_ID}"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"srg_ssr-{JOB_ONE_ID}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "SRG SSR import"
    assert stored["id"] == f"srg_ssr-{JOB_ONE_ID}"
