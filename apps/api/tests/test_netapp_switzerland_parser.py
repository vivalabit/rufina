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
from app.services.parsers.companies.netapp_switzerland import (
    NETAPP_RESULTS_PER_PAGE,
    NETAPP_SWITZERLAND_FACET_ID,
    NetAppSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, foreign: bool = False) -> dict[str, str]:
    job_id = str(98_000_000_000 + index)
    return {
        "job_id": job_id,
        "title": f"NetApp role {index}",
        "location": "Boston, United States" if foreign else "Rotkreuz, Switzerland",
        "category": "Digital Data & Technology",
        "url": f"https://careers.netapp.com/job/rotkreuz/netapp-role-{index}/27600/{job_id}",
    }


def filters_html(total: int, *, checked: bool = True) -> str:
    checked_attribute = ' checked="checked"' if checked else ""
    return f"""
    <section id="search-filters">
      <input type="checkbox" class="filter-checkbox" data-facet-type="2"
        data-id="{NETAPP_SWITZERLAND_FACET_ID}" data-count="{total}"
        data-display="Switzerland" data-field-name=""{checked_attribute} />
    </section>
    """


def results_html(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    organization_id: str = "27600",
) -> str:
    total_pages = (total + NETAPP_RESULTS_PER_PAGE - 1) // NETAPP_RESULTS_PER_PAGE
    cards = "".join(
        f"""
        <li>
          <button class="js-save-job-btn" data-job-id="{record["job_id"]}"
            data-org-id="27600">Save for Later</button>
          <a href="{httpx.URL(record["url"]).path}" data-job-id="{record["job_id"]}">
            <h3>{record["title"]}</h3>
            <span class="job-location"><strong>Location: </strong>{record["location"]}</span>
            <span class="job-category"><strong>Category: </strong>{record["category"]}</span>
          </a>
        </li>
        """
        for record in records
    )
    return f"""
    <section id="search-results" data-total-results="{total}"
      data-total-job-results="{total}" data-total-pages="{total_pages}"
      data-current-page="{page}" data-records-per-page="15"
      data-active-facet-id="{NETAPP_SWITZERLAND_FACET_ID}"
      data-organization-ids="{organization_id}">
      <section id="search-results-list">
        <div class="search-results-list-wrapper"><ul>{cards}</ul></div>
      </section>
    </section>
    """


def listing_response(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    checked: bool = True,
    organization_id: str = "27600",
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
        "hiringOrganization": {"@type": "Organization", "name": "NetApp"},
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Rotkreuz",
                    "addressRegion": "",
                    "addressCountry": "CH",
                },
            }
        ],
    }
    direct_apply = apply_url or (
        "https://jobs.netapp.com/job/Rotkreuz-NetApp-role-6343/"
        f"{record['job_id']}/?feedId=386800&tcsource=apply"
    )
    return f"""
    <html><head>
      <link rel="canonical" href="{record["url"]}" />
      <meta name="search-analytics-currentJobId" content="{record["job_id"]}" />
      <meta name="search-job-apply-url" content="{direct_apply}" />
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head></html>
    """


def parser_with(transport: httpx.BaseTransport, **kwargs: object) -> NetAppSwitzerlandJobsParser:
    return NetAppSwitzerlandJobsParser(transport=transport, **kwargs)


def test_netapp_collects_every_country_page_and_enriches_jobs() -> None:
    records = [listing_record(index) for index in range(16)]
    listing_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            page = payload["CurrentPage"]
            listing_pages.append(page)
            assert request.url.path == "/search-jobs/resultspost"
            assert payload["OrganizationIds"] == "27600"
            assert payload["SearchType"] == 3
            assert payload["ActiveFacetID"] == NETAPP_SWITZERLAND_FACET_ID
            assert payload["FacetFilters"] == [
                {
                    "ID": NETAPP_SWITZERLAND_FACET_ID,
                    "FacetType": 2,
                    "Count": 0 if page == 1 else len(records),
                    "Display": "Switzerland",
                    "IsApplied": True,
                    "FieldName": "",
                }
            ]
            start = (page - 1) * NETAPP_RESULTS_PER_PAGE
            page_records = records[start : start + NETAPP_RESULTS_PER_PAGE]
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
        "Scanned 16 verified NetApp Switzerland vacancies from 16 Radancy country "
        "records across 2 page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "netapp_switzerland"
    assert first.company == "NetApp"
    assert first.location == "Rotkreuz, Switzerland"
    assert first.posted_at == "2026-8-10"
    assert first.employment_type == "Full Time"
    assert first.apply_url and first.apply_url.startswith("https://jobs.netapp.com/job/")
    assert first.description == (
        "Help transform patient care.\n- Build trusted analytics\n- Support the business"
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 16


def test_netapp_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_response([record], total=1, page=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs[0]

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
            listing_response([listing_record(1)], total=1, page=1, organization_id="999"),
            "invalid catalog metadata",
        ),
        (
            listing_response([listing_record(1, foreign=True)], total=1, page=1),
            "incomplete or non-Swiss",
        ),
    ],
)
def test_netapp_rejects_malformed_or_unscoped_catalogs(
    payload: dict[str, object],
    match: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_netapp_rejects_invalid_detail_but_keeps_verified_listing() -> None:
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

    job = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs[0]

    assert job.apply_url == record["url"]
    assert "invalid apply URL" in str(job.raw["detail_error"])


def test_netapp_accepts_verified_empty_catalog() -> None:
    payload = listing_response([], total=0, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 verified NetApp Switzerland vacancies")


def test_netapp_rejects_catalog_above_page_limit() -> None:
    records = [listing_record(index) for index in range(NETAPP_RESULTS_PER_PAGE)]
    payload = listing_response(records, total=31, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser_with(httpx.MockTransport(handler), max_pages=2).search(LinkedInSearchRequest())


def test_netapp_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["netapp_switzerland"]

    assert isinstance(parser, NetAppSwitzerlandJobsParser)
    assert parser.base_url == settings.netapp_switzerland_jobs_base_url
    assert parser.max_pages == settings.netapp_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.netapp_switzerland_jobs_max_catalog_passes
    assert parser.page_workers == settings.netapp_switzerland_jobs_page_workers
    assert parser.detail_workers == settings.netapp_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "NetApp Switzerland", "filters": {}},
            "sources": ["netapp_switzerland", "netapp_switzerland"],
        }
    )
    assert request.sources == ["netapp_switzerland"]

    record = listing_record(1)
    record["detail"] = {
        "title": record["title"],
        "location": record["location"],
        "url": record["url"],
        "apply_url": record["url"],
        "description": "<p>Swiss NetApp role</p>",
    }
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="netapp_switzerland-42680975101",
        added_at=datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "NetApp Switzerland import"
    assert stored["company"] == "NetApp"
