from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.zurich_insurance import (
    ZurichInsuranceJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Zürich, CH",
    search_label: str = "zurich",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <span class="jobTitle hidden-phone">
              <a class="jobTitle-link"
                 href="/job/Zurich-Security-Engineer/{job_id}/">
                Security Engineer {job_id} (m/f/d) 80 - 100%
              </a>
            </span>
            <div class="visible-phone">
              <a class="jobTitle-link"
                 href="/job/Zurich-Security-Engineer/{job_id}/">
                Security Engineer {job_id} (m/f/d) 80 - 100%
              </a>
            </div>
          </td>
          <td class="colDepartment hidden-phone">
            <span class="jobDepartment">IT / Informatik</span>
          </td>
          <td class="colLocation hidden-phone">
            <span class="jobLocation">{location}</span>
          </td>
          <td class="colDate hidden-phone">
            <span class="jobDate">Aug 14, 2026</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <h1 class="keyword-title">Search results for
        <span class="securitySearchQuery"> "{search_label}".</span>
      </h1>
      <div class="paginationLabel">Results {start} – {end} of {total}</div>
      <table id="searchresults"
        aria-label="Search results for {search_label}. Page 1, Results {start} to {end} of {total}">
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def empty_listing_html() -> str:
    return """
    <html><body>
      <h1 class="keyword-title">Search results for
        <span class="securitySearchQuery"> "zurich".</span>
      </h1>
      <div id="noresults" class="alert alert-block">
        <label>There are currently no open positions matching
          <span class="securitySearchString">zurich</span>.</label>
        <div id="noresults-message">
          <label>The 0 most recent jobs posted by Zurich Insurance Company Ltd.
            are listed below for your convenience.</label>
        </div>
      </div>
    </body></html>
    """


def detail_html(
    job_id: int,
    *,
    company: str = "Zurich Insurance Company Ltd.",
    locations: tuple[str, ...] = ("Zürich, CH",),
) -> str:
    addresses = "".join(
        f"""
        <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
          <meta itemprop="streetAddress" content="{location}">
        </span>
        """
        for location in locations
    )
    return f"""
    <html><head>
      <link rel="canonical"
        href="https://www.careers.zurich.test/job/Zurich-Security-Engineer/{job_id}/">
    </head><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
          {addresses}
        </span>
        <meta itemprop="datePosted" content="Fri Aug 14 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{company}">
        <span itemprop="title" data-careersite-propertyid="title">
          Security Engineer {job_id} (m/f/d) 80 - 100%
        </span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Help Zurich protect what people love.</p>
            <h2>Your role</h2>
            <ul><li>Build secure services.</li><li>Lead incident response.</li></ul>
          </span>
        </span>
        <a class="btn apply dialogApplyBtn"
          href="/talentcommunity/apply/{job_id}/?locale=de_DE">Apply now</a>
      </div>
    </body></html>
    """


def parser_with(handler: object, **kwargs: object) -> ZurichInsuranceJobsParser:
    return ZurichInsuranceJobsParser(
        base_url=(
            "https://www.careers.zurich.test/search/?createNewAlert=false&q="
            "&locationsearch=zurich&optionsFacetsDD_shifttype="
            "&optionsFacetsDD_department=&optionsFacetsDD_customfield3="
        ),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kwargs,
    )


def test_zurich_insurance_scans_every_page_and_enriches_jobs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["locationsearch"] == "zurich"
            assert request.url.params["createNewAlert"] == "false"
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                )
            assert offset == 2
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    result = parser_with(handler, detail_workers=2).search(LinkedInSearchRequest())

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 verified Zurich Insurance vacancies from 3 Zürich catalog "
        "records across 2 page requests in 1 catalog pass(es)"
    )
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[1].url.params["startrow"] == "2"

    first = result.jobs[0]
    assert first.source == "zurich_insurance"
    assert first.company == "Zurich Insurance"
    assert first.title == "Security Engineer 101 (m/f/d) 80 - 100%"
    assert first.location == "Zürich, CH"
    assert first.url == ("https://www.careers.zurich.test/job/Zurich-Security-Engineer/101/")
    assert first.apply_url == (
        "https://www.careers.zurich.test/talentcommunity/apply/101/?locale=de_DE"
    )
    assert first.posted_at == "2026-08-14"
    assert first.employment_type == "80-100%"
    assert first.description and "- Build secure services." in first.description
    assert first.raw["department"] == "IT / Informatik"
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3


def test_zurich_insurance_retries_a_shifted_catalog_until_all_ids_are_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/search/":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
            return httpx.Response(200, text=detail_html(job_id))
        offset = int(request.url.params.get("startrow", "0"))
        if offset == 0:
            first_page_calls += 1
            return httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ids = [102] if first_page_calls == 1 else [103]
        return httpx.Response(
            200,
            text=listing_html(ids, start=3, end=3, total=3),
        )

    result = parser_with(handler, detail_workers=1).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests in 2 catalog pass(es)")


def test_zurich_insurance_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = parser_with(handler).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Security Engineer 101 (m/f/d) 80 - 100%"
    assert job.location == "Zürich, CH"
    assert job.posted_at == "2026-08-14"
    assert job.description is None
    assert job.apply_url == (
        "https://www.careers.zurich.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_zurich_insurance_rejects_a_non_swiss_listing_result() -> None:
    parser = parser_with(
        lambda _: httpx.Response(
            200,
            text=listing_html(
                [101],
                start=1,
                end=1,
                total=1,
                location="Zurich, Ontario, CA",
            ),
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_zurich_insurance_rejects_a_listing_without_zurich_scope() -> None:
    parser = parser_with(
        lambda _: httpx.Response(
            200,
            text=listing_html(
                [101],
                start=1,
                end=1,
                total=1,
                search_label="Switzerland",
            ),
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search scope"):
        parser.search(LinkedInSearchRequest())


def test_zurich_insurance_accepts_the_verified_empty_state() -> None:
    parser = parser_with(lambda _: httpx.Response(200, text=empty_listing_html()))

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 verified Zurich Insurance vacancies from 0 Zürich catalog "
        "records across 1 page request in 1 catalog pass(es)"
    )


def test_zurich_insurance_enforces_the_catalog_page_limit() -> None:
    parser = parser_with(
        lambda _: httpx.Response(
            200,
            text=listing_html([101, 102], start=1, end=2, total=3),
        ),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_zurich_insurance_falls_back_when_detail_identity_is_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(200, text=detail_html(101, company="Another Company"))

    job = parser_with(handler).search(LinkedInSearchRequest()).jobs[0]

    assert job.description is None
    assert "different organization" in str(job.raw["detail_error"])


def test_zurich_insurance_keeps_only_swiss_locations_from_multi_location_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(
            200,
            text=detail_html(
                101,
                locations=("Kriens, CH", "Zürich, CH", "London, GB"),
            ),
        )

    job = parser_with(handler).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Kriens, CH; Zürich, CH"
    assert "London" not in job.location


def test_zurich_insurance_is_registered_as_a_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["zurich_insurance"]
    assert isinstance(parser, ZurichInsuranceJobsParser)
    assert parser.base_url == settings.zurich_insurance_jobs_base_url
    assert parser.max_pages == settings.zurich_insurance_jobs_max_pages
    assert parser.max_catalog_passes == settings.zurich_insurance_jobs_max_catalog_passes
    assert parser.detail_workers == settings.zurich_insurance_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Zurich Insurance", "filters": {}},
            "sources": ["zurich_insurance", "zurich_insurance"],
        }
    )
    assert request.sources == ["zurich_insurance"]


def test_zurich_insurance_jobs_render_as_direct_company_imports() -> None:
    job = ZurichInsuranceJobsParser().normalize_job(
        {
            "id": "1369305757",
            "title": "Senior Platform Engineer 80-100%",
            "location": "Zürich, CH",
            "url": ("https://www.careers.zurich.com/job/Zurich-Platform-Engineer/1369305757/"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="zurich_insurance-1369305757",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Zurich Insurance import"
    assert stored["id"] == "zurich_insurance-1369305757"
