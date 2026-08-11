from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.novartis_switzerland import (
    NovartisSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_row(
    job_id: str,
    title: str,
    *,
    country: str = "Switzerland",
    site: str = "Basel (City)",
    alternative: bool = False,
) -> str:
    slug = title.lower().replace(" ", "-").replace("&", "and")
    alt = "+Alternative Locations" if alternative else ""
    return f"""
    <tr>
      <td class="views-field-field-job-title">
        <a href="/careers/career-search/job/details/{job_id}-{slug}">{title}</a>
        Regular, Full time
      </td>
      <td class="views-field-field-job-business-unit">Research</td>
      <td class="views-field-field-job-country">{country}
        <span class="alternative-locations">{alt}</span>
      </td>
      <td class="views-field-field-job-work-location">{site}</td>
      <td class="views-field-field-job-posted-date">Aug 10, 2026</td>
    </tr>
    """


def listing_page(
    rows: list[str],
    *,
    total: int,
    current_page: int,
    total_pages: int,
    swiss_selected: bool = True,
) -> str:
    selected = 'selected="selected"' if swiss_selected else ""
    return f"""
    <html><body>
      <form id="search-listing-filter-form">
        <select name="country[]"><option value="LOC_CH" {selected}>Switzerland</option></select>
      </form>
      <div class="form-item-field-job-posted-date">
        <a class="content-type active" href="?field_job_posted_date=All">All</a>
      </div>
      <div class="view-header">Showing {total} results</div>
      <div class="view-id-career_search"><table class="views-table"><tbody>
        {''.join(rows)}
      </tbody></table></div>
      <nav aria-label="pagination-heading"><ul>
        <li class="active"><a title="page {current_page} active out of {total_pages} pages">
          {current_page}
        </a></li>
      </ul></nav>
    </body></html>
    """


def detail_page(
    job_id: str,
    title: str,
    *,
    country: str = "Switzerland",
    site: str = "Basel (City)",
    alternatives: tuple[str, ...] = (),
    salary: str | None = "CHF78,400.00 - CHF145,600.00",
) -> str:
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "JobPosting",
                "title": title,
                "identifier": job_id.upper(),
                "datePosted": "2026-08-10",
                "employmentType": "Regular",
                "description": "Develop AI systems.",
            }
        ],
    }
    alternative_html = "".join(
        f'<div class="field_alternative_country"><div class="element_items">{value}</div></div>'
        for value in alternatives
    )
    salary_html = (
        f'<div class="field_pay_range"><div class="element_items">{salary}</div></div>'
        if salary
        else ""
    )
    return f"""
    <html><body>
      <article>
        <div class="job_details_content_center">
          <div class="job_description"><h3>Summary</h3><p>Develop AI systems.</p></div>
          <div class="job_description"><h3>About the Role</h3><ul><li>Build models</li></ul></div>
        </div>
        <div class="job_details_content_bottom">
          <div class="field_job_country"><div class="element_items">{country}</div></div>
          <div class="field_job_work_location"><div class="element_items">{site}</div></div>
          {alternative_html}{salary_html}
        </div>
        <a title="Apply to Job" href="https://novartis.wd3.myworkdayjobs.com/en-US/Novartis_Careers/job/{site}/{job_id.upper()}-2">Apply</a>
      </article>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_novartis_scans_all_pages_and_enriches_swiss_locations() -> None:
    second_id = "req-10084558"
    listing_pages: list[int] = []

    # Use distinct IDs on the first page while keeping the compact fixture.
    first_page_rows = [
        listing_row(f"req-{10084379 + index}", f"AI Scientist {index}")
        for index in range(10)
    ]

    def stable_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/careers/career-search":
            query = parse_qs(request.url.query.decode())
            assert query["country[]"] == ["LOC_CH"]
            page = int(query.get("page", ["0"])[0]) + 1
            listing_pages.append(page)
            return httpx.Response(
                200,
                text=(
                    listing_page(first_page_rows, total=11, current_page=1, total_pages=2)
                    if page == 1
                    else listing_page(
                        [
                            listing_row(
                                second_id,
                                "Global Program Head",
                                country="USA",
                                site="East Hanover",
                                alternative=True,
                            )
                        ],
                        total=11,
                        current_page=2,
                        total_pages=2,
                    )
                ),
            )
        match = request.url.path.split("/")[-1]
        normalized_id = "-".join(match.split("-")[:2])
        if normalized_id == second_id:
            return httpx.Response(
                200,
                text=detail_page(
                    second_id,
                    "Global Program Head",
                    country="USA",
                    site="East Hanover",
                    alternatives=("Basel (City), Switzerland",),
                    salary=None,
                ),
            )
        index = int(normalized_id.split("-")[-1]) - 10084379
        return httpx.Response(
            200,
            text=detail_page(normalized_id, f"AI Scientist {index}"),
        )

    result = NovartisSwitzerlandJobsParser(
        base_url="https://www.novartis.com/careers/career-search?country%5B%5D=LOC_CH",
        detail_workers=4,
        transport=httpx.MockTransport(stable_handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert listing_pages == [1, 2]
    assert len(result.jobs) == 11
    assert result.message == (
        "Scanned 11 Novartis Switzerland vacancies across 2 page requests "
        "in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.company == "Novartis"
    assert first.location == "Basel (City), Switzerland"
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "Regular, Full time"
    assert first.description == "Summary\nDevelop AI systems.\n\nAbout the Role\n- Build models"
    assert first.salary == "CHF78,400.00 - CHF145,600.00"
    assert first.salary_min == 78400
    assert first.salary_max == 145600
    assert first.salary_currency == "CHF"
    assert first.salary_unit == "year"
    assert result.jobs[-1].location == "Basel (City), Switzerland"
    assert result.jobs[-1].seniority == "Lead"


def test_novartis_preserves_filtered_listing_when_detail_fails() -> None:
    page = listing_page(
        [listing_row("req-10084379", "AI Scientist")],
        total=1,
        current_page=1,
        total_pages=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page) if request.url.path == "/careers/career-search" else httpx.Response(503)

    job = NovartisSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest()).jobs[0]
    assert job.location == "Basel (City), Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_novartis_rejects_listing_without_swiss_filter() -> None:
    page = listing_page([], total=0, current_page=1, total_pages=1, swiss_selected=False)
    parser = NovartisSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )
    with pytest.raises(DirectCompanyRequestError, match="official Switzerland"):
        parser.search(LinkedInSearchRequest())


def test_novartis_rejects_catalog_that_does_not_stabilize() -> None:
    rows = [
        listing_row(f"req-{10084379 + index}", f"AI Scientist {index}")
        for index in range(10)
    ]
    page = listing_page(rows, total=11, current_page=1, total_pages=2)
    page_two = listing_page([rows[0]], total=11, current_page=2, total_pages=2)

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        return httpx.Response(200, text=page_two if query.get("page") else page)

    parser = NovartisSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="did not stabilize after 2 passes"):
        parser.search(LinkedInSearchRequest())


def test_novartis_rejects_non_swiss_detail_but_keeps_listing() -> None:
    page = listing_page(
        [
            listing_row(
                "req-10084558",
                "Global Program Head",
                country="USA",
                site="East Hanover",
                alternative=True,
            )
        ],
        total=1,
        current_page=1,
        total_pages=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/careers/career-search":
            return httpx.Response(200, text=page)
        return httpx.Response(
            200,
            text=detail_page(
                "req-10084558",
                "Global Program Head",
                country="USA",
                site="East Hanover",
                alternatives=("London, United Kingdom",),
            ),
        )

    job = NovartisSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest()).jobs[0]
    assert job.location == "Switzerland (alternative location)"
    assert "does not contain a Swiss" in str(job.raw["detail_error"])


def test_novartis_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["novartis_switzerland"]
    assert isinstance(parser, NovartisSwitzerlandJobsParser)
    assert parser.base_url == settings.novartis_switzerland_jobs_base_url
    assert parser.max_pages == settings.novartis_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.novartis_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "Novartis", "filters": {}}, "sources": ["novartis_switzerland"]}
    )
    assert request.sources == ["novartis_switzerland"]


def test_novartis_jobs_render_as_direct_company_imports() -> None:
    job = NovartisSwitzerlandJobsParser().normalize_job(
        {
            "id": "req-10084379",
            "title": "AI Scientist",
            "url": (
                "https://www.novartis.com/careers/career-search/job/details/"
                "req-10084379-ai-scientist"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="novartis_switzerland-req-10084379",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Novartis Switzerland import"
