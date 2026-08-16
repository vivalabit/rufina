from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.schindler_switzerland import (
    SchindlerSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://job.schindler.test/search/"


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Ebikon, Lucerne, CH",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="/Schindler/job/Ebikon-Application-Support/{job_id}/">
              Working Student IT Application Support {job_id} (m/w/d) 50-60%
            </a>
          </td>
          <td class="colFacility">
            <span class="jobFacility">Information Technology</span>
          </td>
          <td class="colLocation">
            <span class="jobLocation">{location}</span>
          </td>
          <td class="colDate">
            <span class="jobDate">Aug 15, 2026</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <span class="paginationLabel">Results {start} – {end} of {total}</span>
      <table id="searchresults"
             aria-label="Results {start} to {end} of {total}">
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def detail_html(
    job_id: int,
    *,
    title: str | None = None,
    company: str = "Schindler Group",
    country: str = "CH",
    locality: str = "Ebikon",
    title_class: str = ' class="job-title"',
) -> str:
    job_title = title or f"Working Student IT Application Support {job_id} (m/w/d) 50-60%"
    return f"""
    <html><head>
      <meta property="og:title" content="{job_title}">
    </head><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <span itemprop="jobLocation"><span itemprop="address">
          <meta itemprop="addressLocality" content="{locality}">
          <meta itemprop="addressRegion" content="Luce">
          <meta itemprop="addressCountry" content="{country}">
        </span></span>
        <meta itemprop="datePosted" content="Sat Aug 15 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{company}">
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Join Schindler and help us elevate our world.</p>
            <h1{title_class}><span>{job_title}</span></h1>
            <div id="jobcontent">
              <h4>We Elevate... Your Responsibilities</h4>
              <ul><li>Support the application portfolio.</li></ul>
            </div>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_schindler_scans_full_swiss_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["optionsFacetsDD_country"] == "CH"
            assert request.url.params["locationsearch"] == ""
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                    request=request,
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
                request=request,
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id), request=request)

    result = SchindlerSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 Schindler Switzerland vacancies from 3 catalog records "
        "across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["locale"] == "en_US"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[1].url.params["startrow"] == "2"

    job = result.jobs[0]
    assert job.source == "schindler_switzerland"
    assert job.title == "Working Student IT Application Support 101 (m/w/d) 50-60%"
    assert job.company == "Schindler Group"
    assert job.location == "Ebikon, Lucerne, CH"
    assert job.url == "https://job.schindler.test/Schindler/job/Ebikon-Application-Support/101/"
    assert job.apply_url == (
        "https://job.schindler.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert job.posted_at == "2026-08-15"
    assert job.employment_type == "50–60%"
    assert job.description == (
        "Join Schindler and help us elevate our world.\n\n"
        "Working Student IT Application Support 101 (m/w/d) 50-60%\n\n"
        "We Elevate... Your Responsibilities\n\n"
        "- Support the application portfolio."
    )
    assert job.raw["facility"] == "Information Technology"
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["address_region"] == "Luce"


def test_schindler_retries_shifted_pages_until_all_ids_are_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path == "/search/":
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                first_page_calls += 1
                ids = [101, 102] if first_page_calls == 1 else [101, 103]
                return httpx.Response(
                    200,
                    text=listing_html(ids, start=1, end=2, total=3),
                    request=request,
                )
            return httpx.Response(
                200,
                text=listing_html([101], start=3, end=3, total=3),
                request=request,
            )
        return httpx.Response(503, request=request)

    result = SchindlerSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_schindler_preserves_listing_when_detail_contract_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(101, company="Other Company"),
            request=request,
        )

    job = (
        SchindlerSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Working Student IT Application Support 101 (m/w/d) 50-60%"
    assert job.location == "Ebikon, Lucerne, CH"
    assert job.description is None
    assert job.posted_at == "2026-08-15"
    assert job.apply_url == (
        "https://job.schindler.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert "incomplete or non-Swiss vacancy" in str(job.raw["detail_error"])


def test_schindler_accepts_apprenticeship_description_without_job_title_class() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(101, title_class=""),
            request=request,
        )

    job = (
        SchindlerSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description
    assert "Working Student IT Application Support 101" in job.description
    assert "detail_error" not in job.raw


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (
            listing_html(
                [101],
                start=1,
                end=1,
                total=1,
                location="Berlin, Berlin, DE",
            ),
            "non-Swiss vacancy",
        ),
        ("<html><body>Jobs</body></html>", "search results"),
        (listing_html([101, 101], start=1, end=2, total=2), "duplicate vacancy IDs"),
    ],
)
def test_schindler_rejects_invalid_catalogs(page_html: str, message: str) -> None:
    parser = SchindlerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page_html, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_schindler_enforces_page_limit_and_wraps_http_errors() -> None:
    too_large = SchindlerSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = SchindlerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_schindler_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["schindler_switzerland"]
    assert isinstance(parser, SchindlerSwitzerlandJobsParser)
    assert parser.base_url == settings.schindler_switzerland_jobs_base_url
    assert parser.max_pages == settings.schindler_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.schindler_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == settings.schindler_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Schindler", "filters": {}},
            "sources": ["schindler_switzerland", "schindler_switzerland"],
        }
    )
    assert request.sources == ["schindler_switzerland"]


def test_schindler_jobs_render_as_direct_company_imports() -> None:
    job = SchindlerSwitzerlandJobsParser().normalize_job(
        {
            "id": "1416306233",
            "title": "Working Student IT Application Support (m/w/d) 50-60%",
            "location": "Ebikon, Lucerne, CH",
            "url": (
                "https://job.schindler.com/Schindler/job/Ebikon-Working-Student/"
                "1416306233/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="schindler_switzerland-1416306233",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Schindler Group import"
    assert stored["company"] == "Schindler Group"
    assert stored["id"] == "schindler_switzerland-1416306233"
