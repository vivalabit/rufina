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
from app.services.parsers.companies.ebp_switzerland import (
    EbpSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOB_ONE_ID = "b913f9ef-1bdc-4824-8b46-ea0607c12c58"
JOB_TWO_ID = "7a5f33ef-e1b9-4db5-8db3-c70acb2d8712"


def listing_card(*, job_id: str, slug: str, title: str, workload: str) -> str:
    detail_url = f"https://jobs.ebp.ch/offene-stellen/{slug}/{job_id}"
    return f"""
    <a class="job" href="{detail_url}" title="{title}" target="_blank">
      <h3 class="title">{title}</h3>
      <div class="job-additions">
        <div class="workload">
          <span class="forCHonly">{workload}</span>
          <span class="forDEonly">m/w/d</span>
        </div>
      </div>
    </a>
    """


def listing_page(cards: list[str]) -> str:
    return f"""
    <html><body>
      <main id="content"><div id="jobs">{"".join(cards)}</div></main>
      <div class="footer-jobabo"><a href="jobabo?lang=de">Job-Newsletter</a></div>
    </body></html>
    """


def detail_page(
    *,
    job_id: str,
    title: str,
    city: str,
    workload: str,
    country: str = "Schweiz",
    organization: str = "EBP Schweiz AG",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": f"{title} - im Geschäftsbereich Beratung, {workload}",
        "description": (
            "<h3>Forme mit uns Zukunft als</h3><br>"
            "<p><div>Dein Beitrag in unserem Team</div><br>"
            "Du leitest anspruchsvolle und nachhaltige Projekte.</p><br>"
            "<ul><li>Berate Kundinnen und Kunden</li>"
            "<li>Arbeite interdisziplinär</li></ul>"
        ),
        "datePosted": "2026-08-10",
        "validThrough": "2027-08-09",
        "employmentType": "PART_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": organization,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": city,
            },
        },
    }
    return f"""
    <html><body>
      <div class="content container"><section><h1>{title}</h1></section></div>
      <a title="Jetzt bewerben"
         href="https://ohws.prospective.ch/public/v1/redirect/{job_id}/ats/">
        Jetzt bewerben
      </a>
    </body></html>
    <script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_ebp_scans_complete_filtered_catalog_and_enriches_details() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/":
            assert request.url.params["lang"] == "de"
            assert request.url.params["filter_30"] == "64650"
            assert request.url.params["filter_10"] == "42976"
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id=JOB_ONE_ID,
                            slug="junior-projektleiter-in",
                            title="Junior Projektleiter/in für die Arealentwicklung",
                            workload="70-100%",
                        ),
                        listing_card(
                            job_id=JOB_TWO_ID,
                            slug="assistenz-beratungsprojekte",
                            title="Assistenz Beratungsprojekte",
                            workload="40-70%",
                        ),
                    ]
                ),
            )
        if request.url.path.endswith(JOB_ONE_ID):
            return httpx.Response(
                200,
                text=detail_page(
                    job_id=JOB_ONE_ID,
                    title="Junior Projektleiter/in für die Arealentwicklung",
                    city="Zürich",
                    workload="70-100%",
                ),
            )
        if request.url.path.endswith(JOB_TWO_ID):
            return httpx.Response(
                200,
                text=detail_page(
                    job_id=JOB_TWO_ID,
                    title="Assistenz Beratungsprojekte",
                    city="Zürich",
                    workload="40-70%",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = EbpSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 EBP Switzerland vacancies from the filtered Prospective catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "ebp_switzerland"
    assert first.title == "Junior Projektleiter/in für die Arealentwicklung"
    assert first.company == "EBP Schweiz AG"
    assert first.location == "Zürich, Schweiz"
    assert first.url and first.url.endswith(JOB_ONE_ID)
    assert first.apply_url == (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_ONE_ID}/ats/")
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "70-100%, Part-time"
    assert first.description and "nachhaltige Projekte" in first.description
    assert first.description and "- Berate Kundinnen und Kunden" in first.description
    assert first.raw["workload"] == "70-100%"
    assert first.raw["detail"]["valid_through"] == "2027-08-09"


def test_ebp_preserves_filtered_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id=JOB_ONE_ID,
                            slug="junior-projektleiter-in",
                            title="Junior Projektleiter/in",
                            workload="70-100%",
                        )
                    ]
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        EbpSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Junior Projektleiter/in"
    assert job.location == "Switzerland"
    assert job.apply_url and job.apply_url.endswith(JOB_ONE_ID)
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ebp_rejects_catalog_url_without_official_filters() -> None:
    parser = EbpSwitzerlandJobsParser(
        catalog_url="https://jobs.ebp.ch/?lang=de&filter_30=64650",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="")),
    )

    with pytest.raises(DirectCompanyRequestError, match="official filters"):
        parser.search(LinkedInSearchRequest())


def test_ebp_rejects_incomplete_listing_record() -> None:
    page = listing_page(
        [
            listing_card(
                job_id=JOB_ONE_ID,
                slug="junior-projektleiter-in",
                title="Junior Projektleiter/in",
                workload="",
            )
        ]
    )
    parser = EbpSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_ebp_rejects_non_swiss_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id=JOB_ONE_ID,
                            slug="junior-projektleiter-in",
                            title="Junior Projektleiter/in",
                            workload="70-100%",
                        )
                    ]
                ),
            )
        return httpx.Response(
            200,
            text=detail_page(
                job_id=JOB_ONE_ID,
                title="Junior Projektleiter/in",
                city="Berlin",
                workload="70-100%",
                country="Deutschland",
            ),
        )

    job = (
        EbpSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Switzerland"
    assert job.description is None
    assert "required vacancy data" in str(job.raw["detail_error"])


def test_ebp_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ebp_switzerland"]
    assert isinstance(parser, EbpSwitzerlandJobsParser)
    assert parser.base_url == settings.ebp_switzerland_jobs_base_url
    assert parser.catalog_url == settings.ebp_switzerland_jobs_catalog_url
    assert parser.detail_workers == settings.ebp_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "EBP", "filters": {}},
            "sources": ["ebp_switzerland", "ebp_switzerland"],
        }
    )
    assert request.sources == ["ebp_switzerland"]


def test_ebp_jobs_render_as_direct_company_imports() -> None:
    parser = EbpSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": JOB_ONE_ID,
            "title": "Junior Projektleiter/in",
            "location": "Switzerland",
            "url": (f"https://jobs.ebp.ch/offene-stellen/junior-projektleiter-in/{JOB_ONE_ID}"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"ebp_switzerland-{JOB_ONE_ID}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "EBP Switzerland import"
    assert stored["id"] == f"ebp_switzerland-{JOB_ONE_ID}"
