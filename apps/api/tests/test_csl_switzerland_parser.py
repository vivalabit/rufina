from __future__ import annotations

import html
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.csl_switzerland import (
    CslSwitzerlandJobsParser,
    valid_apply_url,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = (
    "https://jobs.csl.test/en/jobs?filterrific%5Bwith_location3%5D=switzerland"
)


def listing_card(
    job_id: str,
    title: str,
    *,
    location: str = "Bern, Berne, Switzerland",
    employment_type: str = "Full Time",
    company: str = "CSL Behring",
    suffix: str = "",
) -> str:
    url = f"https://jobs.csl.com/en/jobs/{title.lower().replace(' ', '-')}-en-r-{job_id}{suffix}"
    return f"""
      <li>
        <a href="{url}">
          <p>{html.escape(title)}</p>
          <p>{employment_type}</p>
          <p>Quality</p>
          <p>Quality Control</p>
          <p>{company}</p>
          <p>{location}</p>
          <p>R-{job_id}</p>
          <p>Posted on&nbsp;<time datetime="2026-08-14">August 14, 2026</time></p>
        </a>
      </li>
    """


def listing_page(
    cards: list[str],
    *,
    start: int,
    end: int,
    total: int,
) -> str:
    return f"""
      <html><head><title>CSL Careers - Find Your Future Job</title></head><body>
        <div id="results-count"><p>Showing <span>{start}</span> to <span>{end}</span>
          of <span>{total}</span> results</p></div>
        <div id="results"><ul role="list">{''.join(cards)}</ul></div>
      </body></html>
    """


def detail_page(
    job_id: str,
    title: str,
    *,
    location: str = "Bern, Berne, Switzerland",
    employment_type: str = "Full Time",
    company: str = "CSL Behring",
    suffix: str = "",
) -> str:
    url = f"https://jobs.csl.com/en/jobs/{title.lower().replace(' ', '-')}-en-r-{job_id}{suffix}"
    city, *location_parts = location.split(", ")
    region = location_parts[0] if len(location_parts) == 2 else ""
    description = "<p>Lead digital quality systems.</p><ul><li>Support laboratories.</li></ul>"
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-08-14",
        "description": description,
        "employmentType": employment_type.upper().replace(" ", "_"),
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": f"R-{job_id}",
        },
        "hiringOrganization": {"@type": "Organization", "name": "CSL"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city,
                "addressRegion": region,
                "addressCountry": "CH",
            },
        },
    }
    apply_url = (
        f"https://olivia.paradox.ai/co/CSL17/Job?job_id=P1-{job_id}-0&amp;posting_type=1"
    )
    return f"""
      <html><head>
        <link rel="canonical" href="{url}">
        <script type="application/ld+json">{json.dumps(posting)}</script>
      </head><body><main>
        <h1>{html.escape(title)}</h1>
        <div class="description">{description}</div>
        <a class="apply-button" href="{apply_url}">Apply Now</a>
        <a class="apply-button" href="{apply_url}">Apply Now</a>
      </main></body></html>
    """


def test_csl_scans_complete_catalog_and_enriches_jobs() -> None:
    records = {
        "283348": ("Senior-Scientist", "Bern, Berne, Switzerland", "Full Time", ""),
        "282182": ("Quality-Manager", "Glattbrugg, Zürich, Switzerland", "Part Time", "-behring"),
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "jobs.csl.test":
            assert request.url.params["filterrific[with_location3]"] == "switzerland"
            assert request.url.params["filterrific[sorted_by]"] == "newest"
            page = int(request.url.params.get("page", "1"))
            job_id = "283348" if page == 1 else "282182"
            title, location, employment_type, suffix = records[job_id]
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id,
                            title,
                            location=location,
                            employment_type=employment_type,
                            suffix=suffix,
                        )
                    ],
                    start=page,
                    end=page,
                    total=2,
                ),
                request=request,
            )
        job_id = request.url.path.split("-en-r-")[1].split("-")[0]
        title, location, employment_type, suffix = records[job_id]
        return httpx.Response(
            200,
            text=detail_page(
                job_id,
                title,
                location=location,
                employment_type=employment_type,
                suffix=suffix,
            ),
            request=request,
        )

    result = CslSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 CSL Switzerland vacancies from 2 catalog records across 2 page requests"
    )
    assert len(requests) == 4
    job = result.jobs[0]
    assert job.source == "csl_switzerland"
    assert job.title == "Senior-Scientist"
    assert job.company == "CSL Behring"
    assert job.location == "Bern, Berne, Switzerland"
    assert job.url == (
        "https://jobs.csl.com/en/jobs/senior-scientist-en-r-283348"
    )
    assert job.apply_url == (
        "https://olivia.paradox.ai/co/CSL17/Job?job_id=P1-283348-0&posting_type=1"
    )
    assert job.posted_at == "2026-08-14"
    assert job.employment_type == "Full Time"
    assert job.description == "Lead digital quality systems.\n- Support laboratories."
    assert job.raw["detail"]["id"] == "R-283348"
    assert job.raw["total_available"] == 2


def test_csl_preserves_listing_when_detail_fails() -> None:
    title = "Laboratory-Professional"
    catalog = listing_page(
        [listing_card("287218", title)],
        start=1,
        end=1,
        total=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.csl.test":
            return httpx.Response(200, text=catalog, request=request)
        return httpx.Response(503, request=request)

    job = (
        CslSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == title
    assert job.company == "CSL Behring"
    assert job.location == "Bern, Berne, Switzerland"
    assert job.apply_url is None
    assert job.posted_at == "2026-08-14"
    assert "503" in job.raw["detail_error"]


def test_csl_accepts_reference_bound_workday_application_url() -> None:
    url = (
        "https://csl.wd1.myworkdayjobs.com/CSL_External/job/"
        "EMEA-CH-Kanton-Bern-Bern-CSL-Behring/GRA-CMC-Specialist_R-275248-2/apply"
    )

    assert valid_apply_url(url, expected_reference="R-275248") == url
    assert valid_apply_url(url, expected_reference="R-111111") is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("<html></html>", "missing its search results"),
        (
            listing_page(
                [
                    listing_card("283348", "First-Job"),
                    listing_card("283348", "First-Job"),
                ],
                start=1,
                end=2,
                total=2,
            ),
            "malformed or non-Swiss",
        ),
        (
            listing_page(
                [listing_card("283348", "First-Job", location="Berlin, Germany")],
                start=1,
                end=1,
                total=1,
            ),
            "malformed or non-Swiss",
        ),
    ],
)
def test_csl_rejects_invalid_catalogs(payload: str, message: str) -> None:
    parser = CslSwitzerlandJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=payload, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_csl_enforces_page_limit_and_wraps_http_errors() -> None:
    first_page = listing_page(
        [listing_card("283348", "First-Job")],
        start=1,
        end=1,
        total=2,
    )
    too_large = CslSwitzerlandJobsParser(
        base_url=BASE_URL,
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=first_page, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = CslSwitzerlandJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_csl_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["csl_switzerland"]
    assert isinstance(parser, CslSwitzerlandJobsParser)
    assert parser.base_url == settings.csl_switzerland_jobs_base_url
    assert parser.max_pages == settings.csl_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.csl_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.csl_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "CSL Switzerland", "filters": {}},
            "sources": ["csl_switzerland", "csl_switzerland"],
        }
    )
    assert request.sources == ["csl_switzerland"]


def test_csl_jobs_render_as_direct_company_imports() -> None:
    job = CslSwitzerlandJobsParser().normalize_job(
        {
            "id": "283348",
            "reference": "R-283348",
            "title": "Senior Scientist Digital Quality Control",
            "company": "CSL Behring",
            "location": "Bern, Berne, Switzerland",
            "employment_type": "Full Time",
            "posted_at": "2026-08-14",
            "url": (
                "https://jobs.csl.com/en/jobs/"
                "senior-scientist-digital-quality-control-en-r-283348"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="csl_switzerland-283348",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "CSL Switzerland import"
    assert stored["company"] == "CSL Behring"
    assert stored["id"] == "csl_switzerland-283348"
