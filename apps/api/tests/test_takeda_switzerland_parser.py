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
from app.services.parsers.companies.takeda_switzerland import (
    TAKEDA_RESULTS_PER_PAGE,
    TAKEDA_SWITZERLAND_FACET_ID,
    TakedaSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, multiple: bool = False) -> dict[str, str]:
    job_id = str(99_191_848_700 + index)
    return {
        "job_id": job_id,
        "title": f"Takeda role {index}",
        "location": "Multiple Locations" if multiple else "Zurich, Canton of Zurich",
        "category": "Digital Data & Technology",
        "url": f"https://jobs.takeda.com/job/zurich/takeda-role-{index}/1113/{job_id}",
    }


def filters_html(total: int, *, checked: bool = True) -> str:
    checked_attribute = ' checked="checked"' if checked else ""
    return f"""
    <div id="search-filters">
      <input type="checkbox" class="filter-checkbox" data-facet-type="2"
        data-id="{TAKEDA_SWITZERLAND_FACET_ID}" data-count="{total}"
        data-display="Switzerland" data-field-name=""{checked_attribute} />
    </div>
    """


def results_html(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    sort_direction: int = 1,
    card_organization: str = "1113",
) -> str:
    total_pages = (total + TAKEDA_RESULTS_PER_PAGE - 1) // TAKEDA_RESULTS_PER_PAGE
    cards = "".join(
        f"""
        <li>
          <button class="js-save-job-btn" data-job-id="{record['job_id']}"
            data-org-id="{card_organization}">Save for Later</button>
          <a href="{httpx.URL(record['url']).path}" data-job-id="{record['job_id']}">
            <h2 class="title">{record['title']}</h2>
            <span class="location">{record['location']}</span>
            <span class="category"><strong>Category: </strong>{record['category']}</span>
          </a>
        </li>
        """
        for record in records
    )
    applied_filter = (
        f'<button class="filter-button" data-id="{TAKEDA_SWITZERLAND_FACET_ID}" '
        'data-facet-type="2">Switzerland</button>'
        if total
        else ""
    )
    return f"""
    <section id="search-results" data-total-results="{total}"
      data-total-job-results="{total}" data-total-pages="{total_pages}"
      data-current-page="{page}" data-records-per-page="5"
      data-active-facet-id="{TAKEDA_SWITZERLAND_FACET_ID}"
      data-organization-ids="" data-sort-direction="{sort_direction}"
      data-search-type="5">
      {applied_filter}
      <div id="search-results-list"><ul>{cards}</ul></div>
    </section>
    """


def listing_response(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    checked: bool = True,
    sort_direction: int = 1,
    card_organization: str = "1113",
) -> dict[str, object]:
    return {
        "filters": filters_html(total, checked=checked),
        "hasContent": False,
        "hasJobs": total > 0,
        "results": results_html(
            records,
            total=total,
            page=page,
            sort_direction=sort_direction,
            card_organization=card_organization,
        ),
    }


def detail_html(
    record: dict[str, str],
    *,
    swiss: bool = True,
    include_foreign: bool = False,
) -> str:
    locations: list[dict[str, object]] = []
    if swiss:
        locations.append(
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Zurich",
                    "addressRegion": "Zurich",
                    "addressCountry": "Switzerland",
                },
            }
        )
    if include_foreign or not swiss:
        locations.append(
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Cambridge",
                    "addressRegion": "Massachusetts",
                    "addressCountry": "United States",
                },
            }
        )
    posting = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "datePosted": "2026-8-13",
        "description": (
            "<p>Improve health outcomes.</p>"
            "<ul><li>Build trusted systems</li><li>Support patients</li></ul>"
        ),
        "employmentType": "Full time",
        "identifier": f"R{record['job_id']}",
        "title": record["title"],
        "url": record["url"],
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Takeda Pharmaceutical",
        },
        "jobLocation": locations,
    }
    apply_url = (
        "https://takeda.wd502.myworkdayjobs.com/External/job/Zurich-Switzerland/"
        f"Takeda-role-{record['job_id']}_R{record['job_id']}/apply"
    )
    return f"""
    <html><head>
      <meta name="search-analytics-currentJobId" content="{record['job_id']}" />
      <meta name="search-job-apply-url" content="{apply_url}" />
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head></html>
    """


def parser_with(transport: httpx.BaseTransport, **kwargs: object) -> TakedaSwitzerlandJobsParser:
    return TakedaSwitzerlandJobsParser(transport=transport, **kwargs)


def test_takeda_collects_every_country_page_and_enriches_jobs() -> None:
    records = [listing_record(index, multiple=index == 0) for index in range(11)]
    listing_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            page = payload["CurrentPage"]
            listing_pages.append(page)
            assert request.url.path == "/search-jobs/resultspost"
            assert payload["SearchType"] == 5
            assert payload["SortDirection"] == 1
            assert payload["OrganizationIds"] == ""
            assert payload["FacetFilters"][0]["ID"] == TAKEDA_SWITZERLAND_FACET_ID
            start = (page - 1) * TAKEDA_RESULTS_PER_PAGE
            return httpx.Response(
                200,
                json=listing_response(
                    records[start : start + TAKEDA_RESULTS_PER_PAGE],
                    total=len(records),
                    page=page,
                ),
                request=request,
            )
        record = next(item for item in records if request.url.path.endswith(item["job_id"]))
        return httpx.Response(
            200,
            text=detail_html(record, include_foreign=record is records[0]),
            request=request,
        )

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert sorted(listing_pages) == [1, 2, 3]
    assert len(result.jobs) == 11
    assert result.message == (
        "Scanned 11 verified Takeda Switzerland vacancies from 11 Radancy country "
        "records across 3 page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "takeda_switzerland"
    assert first.company == "Takeda Pharmaceutical"
    assert first.location == "Zurich, Zurich, Switzerland"
    assert "United States" not in first.location
    assert first.posted_at == "2026-8-13"
    assert first.employment_type == "Full time"
    assert first.apply_url and first.apply_url.endswith("/apply")
    assert first.description == (
        "Improve health outcomes.\n- Build trusted systems\n- Support patients"
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 11


def test_takeda_preserves_country_scoped_listing_when_detail_fails() -> None:
    record = listing_record(1, multiple=True)

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

    assert job.location == "Switzerland"
    assert job.apply_url == record["url"]
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
                [listing_record(1)], total=1, page=1, sort_direction=0
            ),
            "invalid catalog metadata",
        ),
        (
            listing_response(
                [listing_record(1)], total=1, page=1, card_organization="999"
            ),
            "incomplete vacancy",
        ),
    ],
)
def test_takeda_rejects_malformed_or_unscoped_catalogs(
    payload: dict[str, object],
    match: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_takeda_rejects_foreign_detail_but_keeps_verified_listing() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_response([record], total=1, page=1),
                request=request,
            )
        return httpx.Response(200, text=detail_html(record, swiss=False), request=request)

    job = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    ).jobs[0]

    assert job.location == "Zurich, Canton of Zurich, Switzerland"
    assert "non-Swiss JobPosting" in str(job.raw["detail_error"])


def test_takeda_accepts_verified_empty_catalog() -> None:
    payload = listing_response([], total=0, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 verified Takeda Switzerland vacancies")


def test_takeda_rejects_catalog_above_page_limit() -> None:
    records = [listing_record(index) for index in range(TAKEDA_RESULTS_PER_PAGE)]
    payload = listing_response(records, total=11, page=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser_with(httpx.MockTransport(handler), max_pages=2).search(
            LinkedInSearchRequest()
        )


def test_takeda_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["takeda_switzerland"]

    assert isinstance(parser, TakedaSwitzerlandJobsParser)
    assert parser.base_url == settings.takeda_switzerland_jobs_base_url
    assert parser.max_pages == settings.takeda_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.takeda_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Takeda Switzerland", "filters": {}},
            "sources": ["takeda_switzerland", "takeda_switzerland"],
        }
    )
    assert request.sources == ["takeda_switzerland"]

    record = listing_record(1)
    record["detail"] = {
        "title": record["title"],
        "location": "Zurich, Zurich, Switzerland",
        "url": record["url"],
        "apply_url": record["url"],
        "description": "<p>Swiss Takeda role</p>",
    }
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="takeda_switzerland-99191848701",
        added_at=datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Takeda Switzerland import"
    assert stored["company"] == "Takeda Pharmaceutical"
