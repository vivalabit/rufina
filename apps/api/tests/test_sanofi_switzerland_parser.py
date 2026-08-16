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
from app.services.parsers.companies.sanofi_switzerland import (
    SANOFI_RESULTS_PER_PAGE,
    SANOFI_SWITZERLAND_FACET_ID,
    SanofiSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, foreign: bool = False) -> dict[str, str]:
    job_id = str(42_680_975_100 + index)
    return {
        "job_id": job_id,
        "title": f"Sanofi role {index}",
        "location": "Boston, United States" if foreign else "Rotkreuz, Switzerland",
        "category": "Digital Data & Technology",
        "url": f"https://jobs.sanofi.com/en/job/rotkreuz/sanofi-role-{index}/2649/{job_id}",
    }


def filters_html(total: int, *, checked: bool = True) -> str:
    checked_attribute = ' checked="checked"' if checked else ""
    return f"""
    <section id="search-filters">
      <input type="checkbox" class="filter-checkbox" data-facet-type="2"
        data-id="{SANOFI_SWITZERLAND_FACET_ID}" data-count="{total}"
        data-display="Switzerland" data-field-name=""{checked_attribute} />
    </section>
    """


def results_html(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    organization_id: str = "2649",
) -> str:
    total_pages = (total + SANOFI_RESULTS_PER_PAGE - 1) // SANOFI_RESULTS_PER_PAGE
    cards = "".join(
        f"""
        <li>
          <button class="js-save-job-btn" data-job-id="{record['job_id']}"
            data-org-id="2649">Save for Later</button>
          <a href="{httpx.URL(record['url']).path}" data-job-id="{record['job_id']}">
            <h2>{record['title']}</h2>
            <span class="job-location"><strong>Location: </strong>{record['location']}</span>
            <span class="job-category"><strong>Category: </strong>{record['category']}</span>
          </a>
        </li>
        """
        for record in records
    )
    return f"""
    <section id="search-results" data-total-results="{total}"
      data-total-job-results="{total}" data-total-pages="{total_pages}"
      data-current-page="{page}" data-records-per-page="15"
      data-active-facet-id="{SANOFI_SWITZERLAND_FACET_ID}"
      data-organization-ids="{organization_id}">
      <div id="search-results-list"><ul>{cards}</ul></div>
    </section>
    """


def listing_response(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    checked: bool = True,
    organization_id: str = "2649",
) -> dict[str, object]:
    return {
        "filters": filters_html(total, checked=checked),
        "hasContent": False,
        "hasJobs": total > 0,
        "results": results_html(
            records,
            total=total,
            page=page,
            organization_id=organization_id,
        ),
    }


def detail_html(record: dict[str, str], *, apply_url: str | None = None) -> str:
    posting = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "datePosted": "2026-8-10",
        "description": (
            "<p>Help transform patient care.</p>"
            "<ul><li>Build trusted analytics</li><li>Support the business</li></ul>"
        ),
        "employmentType": "Full Time",
        "identifier": f"R{record['job_id']}",
        "title": record["title"],
        "url": record["url"],
        "directApply": "True",
        "hiringOrganization": {"@type": "Organization", "name": "Sanofi"},
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Rotkreuz",
                    "addressRegion": "",
                    "addressCountry": "Switzerland",
                },
            }
        ],
    }
    direct_apply = apply_url or (
        "https://sanofi.wd3.myworkdayjobs.com/SanofiCareers/job/Rotkreuz/"
        f"Sanofi-role-{record['job_id']}_R{record['job_id']}/apply"
    )
    return f"""
    <html><head>
      <link rel="canonical" href="{record['url']}" />
      <meta name="search-analytics-currentJobId" content="{record['job_id']}" />
      <meta name="search-job-apply-url" content="{direct_apply}" />
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head></html>
    """


def parser_with(transport: httpx.BaseTransport, **kwargs: object) -> SanofiSwitzerlandJobsParser:
    return SanofiSwitzerlandJobsParser(transport=transport, **kwargs)


def test_sanofi_collects_every_country_page_and_enriches_jobs() -> None:
    records = [listing_record(index) for index in range(16)]
    listing_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            page = payload["CurrentPage"]
            listing_pages.append(page)
            assert request.url.path == "/en/search-jobs/resultspost"
            assert payload["OrganizationIds"] == "2649"
            assert payload["FacetFilters"] == [
                {
                    "ID": SANOFI_SWITZERLAND_FACET_ID,
                    "FacetType": 2,
                    "Count": 0 if page == 1 else len(records),
                    "Display": "Switzerland",
                    "IsApplied": True,
                    "FieldName": "",
                }
            ]
            start = (page - 1) * SANOFI_RESULTS_PER_PAGE
            page_records = records[start : start + SANOFI_RESULTS_PER_PAGE]
            return httpx.Response(
                200,
                json=listing_response(page_records, total=len(records), page=page),
                request=request,
            )
        record = next(item for item in records if request.url.path.endswith(item["job_id"]))
        return httpx.Response(200, text=detail_html(record), request=request)

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert sorted(listing_pages) == [1, 2]
    assert len(result.jobs) == 16
    assert result.message == (
        "Scanned 16 verified Sanofi Switzerland vacancies from 16 Radancy country "
        "records across 2 page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "sanofi_switzerland"
    assert first.company == "Sanofi"
    assert first.location == "Rotkreuz, Switzerland"
    assert first.posted_at == "2026-8-10"
    assert first.employment_type == "Full Time"
    assert first.apply_url and first.apply_url.endswith("/apply")
    assert first.description == (
        "Help transform patient care.\n- Build trusted analytics\n- Support the business"
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 16


def test_sanofi_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_response([record], total=1, page=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    ).jobs[0]

    assert job.title == record["title"]
    assert job.location == "Rotkreuz, Switzerland"
    assert job.url == record["url"]
    assert job.apply_url == record["url"]
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"filters": "x", "hasJobs": True}, "missing results HTML"),
        (
            listing_response([listing_record(1)], total=1, page=1, checked=False),
            "did not preserve",
        ),
        (
            listing_response(
                [listing_record(1)], total=1, page=1, organization_id="999"
            ),
            "invalid catalog metadata",
        ),
        (
            listing_response([listing_record(1, foreign=True)], total=1, page=1),
            "incomplete or non-Swiss",
        ),
    ],
)
def test_sanofi_rejects_malformed_or_unscoped_catalogs(
    payload: dict[str, object],
    match: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_sanofi_rejects_invalid_detail_but_keeps_verified_listing() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_response([record], total=1, page=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(record, apply_url="https://attacker.example/apply"),
            request=request,
        )

    job = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    ).jobs[0]

    assert job.apply_url == record["url"]
    assert "invalid apply URL" in str(job.raw["detail_error"])


def test_sanofi_accepts_verified_empty_catalog() -> None:
    payload = listing_response([], total=0, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 verified Sanofi Switzerland vacancies")


def test_sanofi_rejects_catalog_above_page_limit() -> None:
    records = [listing_record(index) for index in range(SANOFI_RESULTS_PER_PAGE)]
    payload = listing_response(records, total=31, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser_with(httpx.MockTransport(handler), max_pages=2).search(
            LinkedInSearchRequest()
        )


def test_sanofi_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["sanofi_switzerland"]

    assert isinstance(parser, SanofiSwitzerlandJobsParser)
    assert parser.base_url == settings.sanofi_switzerland_jobs_base_url
    assert parser.max_pages == settings.sanofi_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.sanofi_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Sanofi Switzerland", "filters": {}},
            "sources": ["sanofi_switzerland", "sanofi_switzerland"],
        }
    )
    assert request.sources == ["sanofi_switzerland"]

    record = listing_record(1)
    record["detail"] = {
        "title": record["title"],
        "location": record["location"],
        "url": record["url"],
        "apply_url": record["url"],
        "description": "<p>Swiss Sanofi role</p>",
    }
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="sanofi_switzerland-42680975101",
        added_at=datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Sanofi Switzerland import"
    assert stored["company"] == "Sanofi"
