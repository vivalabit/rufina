from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.esurance import EsuranceJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://esurance.ch/work-with-us/?lang=en"
JOB_IDS = ("2759674", "2708252")


def listing_card(
    index: int,
    *,
    job_id: str | None = None,
    location: str | None = None,
) -> str:
    resolved_id = job_id or JOB_IDS[index]
    title = (
        "Agile Operations Lead (80-100%)"
        if index == 0
        else "Full-Stack Engineer (React + Node.js) (80-100%)"
    )
    department = "Operations" if index == 0 else "IT"
    resolved_location = location or ("Zurich, Hybrid" if index == 0 else "Poland, Remote Only")
    return f"""
      <div class="es-bar es-bar--job">
        <div class="es-bar-item font-weight-semibold">{title}</div>
        <div class="es-bar-item">{department}</div>
        <div class="es-bar-item">{resolved_location}</div>
        <div class="es-bar-item text-right">
          <a class="es-cta" href="https://esurance.jobs.personio.com/job/{resolved_id}?language=en">
            See Job Description
          </a>
        </div>
      </div>
    """


def listing_html(
    cards: list[str] | None = None,
    *,
    site_name: str = "esurance",
) -> str:
    content = "".join([listing_card(0), listing_card(1)] if cards is None else cards)
    return f"""
      <!doctype html>
      <html lang="en-US">
        <head>
          <title>esurance | we care for people who care</title>
          <link rel="canonical" href="{BASE_URL}">
          <meta property="og:title" content="Work With Us">
          <meta property="og:site_name" content="{site_name}">
        </head>
        <body>
          <div class="masthead"><a class="logo"><img alt="esurance logo"></a></div>
          <section id="open-positions" class="es-section">
            <div class="container">
              <div class="section-title"><h2>Open positions</h2></div>
              <div class="es-bars">{content}</div>
              <a class="sec-es-jobs--button"
                 href="https://esurance.jobs.personio.com/?language=en">Join the Team</a>
            </div>
          </section>
        </body>
      </html>
    """


def job_posting(index: int, *, country: str | None = None) -> dict[str, Any]:
    job_id = JOB_IDS[index]
    return {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": (
            "Agile Operations Lead" if index == 0 else "Full-Stack Engineer (React + Node.js)"
        ),
        "description": (
            "<h1>Job profile</h1><p>Join esurance and build uncomplicated insurance "
            "experiences with an ambitious, product-driven team.</p>"
            "<h1>What you will do</h1><ul><li>Own measurable outcomes and ship "
            "reliable improvements for our customers.</li></ul>"
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": "esurance AG",
            "value": f"{job_id}-130701",
        },
        "hiringOrganization": {
            "@type": "Organization",
            "name": "esurance AG",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Zürich" if index == 0 else "Krakow",
                "addressCountry": country or ("CH" if index == 0 else "PL"),
            },
        },
        "datePosted": f"2026-08-{19 - index:02d}",
        "employmentType": ["FULL_TIME", "PART_TIME"] if index == 0 else ["FULL_TIME"],
    }


def detail_html(index: int, *, posting: dict[str, Any] | None = None) -> str:
    job_id = JOB_IDS[index]
    payload = posting or job_posting(index)
    title = payload["title"]
    url = f"https://esurance.jobs.personio.com/job/{job_id}?language=en"
    return f"""
      <!doctype html>
      <html lang="en">
        <head>
          <title>{title} | Jobs at esurance AG</title>
          <link rel="canonical" href="{url}">
          <meta property="og:title" content="{title} | Jobs at esurance AG">
        </head>
        <body>
          <script type="application/ld+json">{json.dumps(payload)}</script>
          <a href="/job/{job_id}/apply?language=en">Apply for this job</a>
        </body>
      </html>
    """


def parser_for(
    *,
    page: str | None = None,
    details: dict[str, str | int] | None = None,
    page_status: int = 200,
    **kwargs: Any,
) -> tuple[EsuranceJobsParser, list[str]]:
    requests: list[str] = []
    detail_values = details or {
        JOB_IDS[0]: detail_html(0),
        JOB_IDS[1]: detail_html(1),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "esurance.ch":
            return httpx.Response(page_status, text=page or listing_html(), request=request)
        job_id = request.url.path.rstrip("/").split("/")[-1]
        value = detail_values[job_id]
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        return httpx.Response(200, text=value, request=request)

    return (
        EsuranceJobsParser(
            base_url=BASE_URL,
            detail_workers=1,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
        requests,
    )


def test_esurance_scans_complete_catalog_and_enriches_personio_details() -> None:
    parser, requests = parser_for()

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 esurance vacancies from the complete visible official careers catalog"
    )
    assert requests == [
        "esurance.ch/work-with-us/",
        "esurance.jobs.personio.com/job/2759674",
        "esurance.jobs.personio.com/job/2708252",
    ]
    assert [job.title for job in result.jobs] == [
        "Agile Operations Lead",
        "Full-Stack Engineer (React + Node.js)",
    ]

    first = result.jobs[0]
    assert first.source == "esurance"
    assert first.company == "esurance AG"
    assert first.location == "Zurich, Hybrid"
    assert first.url == "https://esurance.jobs.personio.com/job/2759674?language=en"
    assert first.apply_url == ("https://esurance.jobs.personio.com/job/2759674/apply?language=en")
    assert first.posted_at == "2026-08-19"
    assert first.employment_type == "Full-time / Part-time (80–100%)"
    assert first.description == (
        "Job profile\nJoin esurance and build uncomplicated insurance experiences with an "
        "ambitious, product-driven team.\nWhat you will do\n- Own measurable outcomes "
        "and ship reliable improvements for our customers."
    )
    assert first.raw["department"] == "Operations"
    assert first.raw["detail"]["location_country"] == "CH"

    second = result.jobs[1]
    assert second.location == "Poland, Remote Only"
    assert second.employment_type == "Full-time (80–100%)"
    assert second.raw["detail"]["location_country"] == "PL"


def test_esurance_preserves_listing_when_personio_detail_fails() -> None:
    parser, _ = parser_for(
        page=listing_html([listing_card(0)]),
        details={JOB_IDS[0]: 503},
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Agile Operations Lead (80-100%)"
    assert job.location == "Zurich, Hybrid"
    assert job.apply_url == job.url
    assert job.posted_at is None
    assert job.employment_type == "80–100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_esurance_accepts_explicit_empty_catalog() -> None:
    parser, requests = parser_for(page=listing_html([]), details={})

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 esurance vacancies from the complete visible official careers catalog"
    )
    assert requests == ["esurance.ch/work-with-us/"]


def test_esurance_rejects_page_identity_and_listing_inconsistencies() -> None:
    parser, _ = parser_for(page=listing_html(site_name="Another Company"))
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    duplicate_page = listing_html([listing_card(0), listing_card(1, job_id=JOB_IDS[0])])
    parser, _ = parser_for(page=duplicate_page)
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        parser.search(LinkedInSearchRequest())

    malformed = listing_html([listing_card(0).replace("Operations", "")])
    parser, _ = parser_for(page=malformed)
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy card"):
        parser.search(LinkedInSearchRequest())


def test_esurance_rejects_inconsistent_personio_detail_without_losing_listing() -> None:
    wrong_posting = job_posting(0, country="DE")
    parser, _ = parser_for(
        page=listing_html([listing_card(0)]),
        details={JOB_IDS[0]: detail_html(0, posting=wrong_posting)},
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Agile Operations Lead (80-100%)"
    assert job.description is None
    assert "inconsistent vacancy data" in str(job.raw["detail_error"])


def test_esurance_enforces_catalog_limit_and_wraps_page_http_errors() -> None:
    parser, _ = parser_for(max_jobs=1)
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parser.search(LinkedInSearchRequest())

    parser, _ = parser_for(page_status=503)
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_esurance_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["esurance"]
    assert isinstance(parser, EsuranceJobsParser)
    assert parser.base_url == settings.esurance_jobs_base_url
    assert parser.max_jobs == settings.esurance_jobs_max_jobs
    assert parser.detail_workers == settings.esurance_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "esurance", "filters": {}},
            "sources": ["esurance", "esurance"],
        }
    )
    assert request.sources == ["esurance"]


def test_esurance_jobs_render_as_direct_company_imports() -> None:
    parser, _ = parser_for(page=listing_html([listing_card(0)]))
    job = parser.search(LinkedInSearchRequest()).jobs[0]
    stored = parsed_job_to_stored_job(
        job,
        job_id="esurance-https-esurance-jobs-personio-com-job-2759674",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "esurance AG import"
    assert stored["id"] == "esurance-https-esurance-jobs-personio-com-job-2759674"
