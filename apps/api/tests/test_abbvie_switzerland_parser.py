from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.abbvie_switzerland import (
    AbbVieSwitzerlandJobsParser,
    normalize_job,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy_record(index: int) -> dict[str, str]:
    internal_id = str(31_800 + index)
    external_id = f"R{1_484_420 + index:08d}"
    reference = f"eb2126c2-0ef1-4c74-9d78-{index:012x}"
    slug = f"market-access-manager-{index}"
    return {
        "internal_id": internal_id,
        "external_id": external_id,
        "reference": reference,
        "slug": slug,
        "title": f"Market Access Manager {index}",
        "location": "Cham, ZG",
        "employment_type": "Full-time",
        "function": "Commercial",
        "experience_level": "Mid-Senior Level",
        "work_location_type": "Hybrid",
    }


def job_url(record: dict[str, str]) -> str:
    return f"https://careers.abbvie.com/en/job/{record['slug']}-jid-{record['internal_id']}"


def vacancy_tile(
    record: dict[str, str],
    *,
    country_class: str = "attrax-vacancy-tile--switzerland",
    host: str = "careers.abbvie.com",
) -> str:
    return f"""
    <div class="attrax-vacancy-tile {country_class} attrax-vacancy-tile--abbvie"
         data-jobid="{record["internal_id"]}">
      <a class="attrax-vacancy-tile__title" href="https://{host}/en/job/{record["slug"]}-jid-{record["internal_id"]}">
        {record["title"]}
      </a>
      <div class="attrax-vacancy-tile__location-freetext">
        <p class="attrax-vacancy-tile__item-value">{record["location"]}</p>
      </div>
      <div class="attrax-vacancy-tile__option-work-location-type">
        <p class="attrax-vacancy-tile__item-value">{record["work_location_type"]}</p>
      </div>
      <div class="attrax-vacancy-tile__option-job-type">
        <p class="attrax-vacancy-tile__item-value">{record["employment_type"]}</p>
      </div>
      <div class="attrax-vacancy-tile__option-function">
        <p class="attrax-vacancy-tile__item-value">{record["function"]}</p>
      </div>
      <div class="attrax-vacancy-tile__option-experience-level">
        <p class="attrax-vacancy-tile__item-value">{record["experience_level"]}</p>
      </div>
      <div class="attrax-vacancy-tile__description">
        <p class="attrax-vacancy-tile__item-value">Deliver innovative medicines and solutions.</p>
      </div>
      <div class="attrax-vacancy-tile__reference">
        <p class="attrax-vacancy-tile__item-value">{record["reference"]}</p>
      </div>
      <div class="attrax-vacancy-tile__externalreference">
        <p class="attrax-vacancy-tile__item-value">{record["external_id"]}</p>
      </div>
    </div>
    """


def listing_html(
    records: list[dict[str, str]],
    *,
    total: int,
    facet_total: int | None = None,
    title: str = "Job Search | AbbVie",
    country_class: str = "attrax-vacancy-tile--switzerland",
) -> str:
    facet_total = total if facet_total is None else facet_total
    return f"""
    <html><head><title>{title}</title>
      <link rel="canonical" href="https://careers.abbvie.com/en/jobs">
    </head><body><h1>Job Results</h1>
      <span class="attrax-pagination__total-results">{total} result(s)</span>
      <input name="location-latitude" value="47.3768866">
      <input name="location-longitude" value="8.541694">
      <input name="location-name" value="Zürich, Switzerland">
      <input name="location-radius" value="100">
      <li data-option-id="17445">
        <span class="filter-text">Switzerland</span>
        <span class="filter-count">({facet_total})</span>
      </li>
      {"".join(vacancy_tile(record, country_class=country_class) for record in records)}
      <span class="attrax-pagination__total-results">{total} result(s)</span>
    </body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    title: str | None = None,
    country_locality: str | None = None,
    apply_host: str = "careers.abbvie.com",
) -> str:
    detail_title = title or record["title"]
    posting = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "url": job_url(record),
        "title": detail_title,
        "description": (
            "<div>Company Description</div><p>AbbVie discovers and delivers "
            "innovative medicines and solutions that solve serious health issues.</p>"
            "<div>Job Description</div><p>Develop customized value propositions, "
            "collaborate across teams, and support patients in Switzerland.</p>"
        ),
        "datePosted": "2026-08-18T06:57:07+00:00",
        "employmentType": [record["employment_type"]],
        "hiringOrganization": {"@type": "Organization", "name": "AbbVie"},
        "identifier": {
            "@type": "PropertyValue",
            "name": "AbbVie",
            "value": record["reference"],
        },
        "industry": [record["function"]],
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": country_locality or record["location"],
                },
            }
        ],
    }
    apply_url = (
        f"https://{apply_host}/en/Workflow?"
        "workflowId=e8d1d8bf-3e41-4c99-90d1-f7ed5600206e&"
        f"vacancyId={record['internal_id']}"
    )
    return f"""
    <html><head><link rel="canonical" href="{job_url(record)}">
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head><body><h1>{detail_title}</h1>
      <a class="jobApplyBtn" href="{apply_url}">Apply</a>
      <a class="jobApplyBtn" href="{apply_url}">Apply</a>
    </body></html>
    """


def test_abbvie_scans_every_page_and_enriches_all_jobs() -> None:
    records = [vacancy_record(index) for index in range(12)]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/en/jobs":
            page = int(request.url.params["page"])
            page_records = records[:10] if page == 1 else records[10:]
            return httpx.Response(200, text=listing_html(page_records, total=12))
        record = next(item for item in records if request.url.path == url_path(job_url(item)))
        return httpx.Response(200, text=detail_html(record))

    result = AbbVieSwitzerlandJobsParser(
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len([url for url in calls if "/en/jobs?" in url]) == 2
    assert len([url for url in calls if "/en/job/" in url]) == 12
    assert result.message == (
        "Scanned 12 AbbVie Switzerland vacancies from the complete Zürich-area Attrax catalog"
    )
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "abbvie_switzerland"
    assert first.title == "Market Access Manager 0"
    assert first.company == "AbbVie AG"
    assert first.location == "Cham, ZG, Switzerland"
    assert first.url == job_url(records[0])
    assert first.apply_url == (
        "https://careers.abbvie.com/en/Workflow?"
        "workflowId=e8d1d8bf-3e41-4c99-90d1-f7ed5600206e&vacancyId=31800"
    )
    assert first.posted_at == "2026-08-18T06:57:07+00:00"
    assert first.employment_type == "Full-time"
    assert first.seniority == "Mid-Senior Level"
    assert first.description and first.description.startswith("Company Description")
    assert first.raw["id"] == "R01484420"
    assert first.raw["reference"] == "eb2126c2-0ef1-4c74-9d78-000000000000"
    assert first.raw["catalog_total"] == 12


def test_abbvie_preserves_verified_listing_when_detail_fails() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs":
            return httpx.Response(200, text=listing_html([record], total=1))
        return httpx.Response(503, text="unavailable")

    job = (
        AbbVieSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == record["title"]
    assert job.location == "Cham, ZG, Switzerland"
    assert job.apply_url == job_url(record)
    assert job.description == "Deliver innovative medicines and solutions."
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (listing_html([], total=0, title="Generic careers"), "unexpected identity"),
        (listing_html([vacancy_record(0)], total=1, facet_total=2), "facet"),
        (
            listing_html(
                [vacancy_record(0)],
                total=1,
                country_class="attrax-vacancy-tile--germany",
            ),
            "out-of-scope",
        ),
    ],
)
def test_abbvie_rejects_untrusted_catalogs(page_html: str, message: str) -> None:
    parser = AbbVieSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page_html))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_abbvie_rejects_duplicate_and_oversized_catalogs() -> None:
    record = vacancy_record(0)
    duplicate = AbbVieSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([record, record], total=2))
        )
    )
    oversized = AbbVieSwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([record, vacancy_record(1)], total=2),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="does not reconcile"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_abbvie_enforces_page_limit() -> None:
    records = [vacancy_record(index) for index in range(11)]
    parser = AbbVieSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(records[:10], total=11))
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="requires 2 pages"):
        parser.search(LinkedInSearchRequest())


def test_abbvie_keeps_listing_when_detail_is_invalid() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs":
            return httpx.Response(200, text=listing_html([record], total=1))
        return httpx.Response(200, text=detail_html(record, title="Different role"))

    job = (
        AbbVieSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.title == record["title"]
    assert "invalid vacancy identity" in str(job.raw["detail_error"])


def test_abbvie_accepts_explicit_empty_catalog() -> None:
    result = AbbVieSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html([], total=0)))
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 AbbVie Switzerland vacancies")


def test_abbvie_wraps_listing_request_failures() -> None:
    parser = AbbVieSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_abbvie_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["abbvie_switzerland"]

    assert isinstance(parser, AbbVieSwitzerlandJobsParser)
    assert parser.base_url == settings.abbvie_switzerland_jobs_base_url
    assert parser.max_pages == settings.abbvie_switzerland_jobs_max_pages
    assert parser.max_jobs == settings.abbvie_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.abbvie_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AbbVie Switzerland", "filters": {}},
            "sources": ["abbvie_switzerland", "abbvie_switzerland"],
        }
    )
    assert request.sources == ["abbvie_switzerland"]

    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["external_id"],
                "title": record["title"],
                "location": "Cham, ZG, Switzerland",
                "employment_type": record["employment_type"],
                "experience_level": record["experience_level"],
                "description": "Develop medicines.",
                "url": job_url(record),
            }
        ),
        job_id=f"abbvie_switzerland-{record['external_id']}",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "AbbVie Switzerland import"
    assert stored["company"] == "AbbVie AG"


def url_path(value: str) -> str:
    return httpx.URL(value).path
