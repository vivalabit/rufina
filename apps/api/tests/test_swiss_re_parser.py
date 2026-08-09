from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.swiss_re import SwissReJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    country: str = "CH",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <span class="jobTitle hidden-phone">
              <a class="jobTitle-link"
                 href="/job/Zurich-Security-Analyst-Zuri/{job_id}/">
                Security Analyst {job_id}
              </a>
            </span>
            <div class="visible-phone">
              <a class="jobTitle-link"
                 href="/job/Zurich-Security-Analyst-Zuri/{job_id}/">
                Security Analyst {job_id}
              </a>
            </div>
          </td>
          <td class="colLocation hidden-phone">
            <span class="jobLocation">Zurich, Zurich, {country}</span>
          </td>
          <td class="colDate hidden-phone"><span class="jobDate">5 Aug 2026</span></td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <div class="paginationLabel">Results {start} – {end} of {total}</div>
      <table id="searchresults"
        aria-label="Search results for Switzerland. Results {start} to {end} of {total}">
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def detail_html(job_id: int, *, title: str | None = None) -> str:
    job_title = title or f"Security Analyst {job_id} (Hybrid, 80-100%)"
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Wed Aug 05 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="Swiss Re">
        <span itemprop="jobLocation"><span itemprop="address">
          <meta itemprop="addressLocality" content="Zurich">
          <meta itemprop="addressCountry" content="CH">
        </span></span>
        <span itemprop="title" data-careersite-propertyid="title">{job_title}</span>
        <span data-careersite-propertyid="location">
          <span class="jobGeoLocation">Zurich, Zurich, CH</span>
        </span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Help Swiss Re make the world more resilient.</p>
            <h2>About the role</h2>
            <ul><li>Monitor security events.</li><li>Lead incident response.</li></ul>
            <p>For Switzerland the base salary range for this position is between
               CHF 128,000 and CHF 192,000 (for a full-time role).</p>
          </span>
        </span>
        <span itemprop="industry">Technology</span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_GB">Apply now</a>
      </div>
    </body></html>
    """


def test_swiss_re_scans_swiss_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["locationsearch"] == "Switzerland"
            assert request.url.params["locale"] == "en_GB"
            assert request.url.params["sortColumn"] == "referencedate"
            assert request.url.params["sortDirection"] == "desc"
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = SwissReJobsParser(
        base_url="https://www.swissre.test/careers/switzerland-careers.html",
        search_url="https://careers.swissre.test/search/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.search_url.endswith("/careers/switzerland-careers.html")
    assert result.message == (
        "Scanned 3 Swiss Re vacancies from 3 Swiss catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "swiss_re"
    assert first.title == "Security Analyst 101 (Hybrid, 80-100%)"
    assert first.company == "Swiss Re"
    assert first.location == "Zurich, Zurich, CH"
    assert first.url == ("https://careers.swissre.test/job/Zurich-Security-Analyst-Zuri/101/")
    assert first.apply_url == (
        "https://careers.swissre.test/talentcommunity/apply/101/?locale=en_GB"
    )
    assert first.posted_at == "2026-08-05"
    assert first.employment_type == "80-100%"
    assert first.description and "- Monitor security events." in first.description
    assert first.salary == "CHF 128,000–192,000 per year"
    assert first.salary_min == 128_000
    assert first.salary_max == 192_000
    assert first.salary_currency == "CHF"
    assert first.salary_unit == "year"
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["job_segment"] == "Technology"


def test_swiss_re_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/search/":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
            return httpx.Response(200, text=detail_html(job_id))

        offset = int(request.url.params.get("startrow", "0"))
        if offset == 0:
            first_page_calls += 1
            ids = [101, 102]
            start, end = 1, 2
        else:
            ids = [102] if first_page_calls == 1 else [103]
            start = end = 3
        return httpx.Response(
            200,
            text=listing_html(ids, start=start, end=end, total=3),
        )

    parser = SwissReJobsParser(
        search_url="https://careers.swissre.test/search/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_swiss_re_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SwissReJobsParser(
        search_url="https://careers.swissre.test/search/",
        transport=httpx.MockTransport(handler),
    )
    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Security Analyst 101"
    assert job.location == "Zurich, Zurich, CH"
    assert job.posted_at == "2026-08-05"
    assert job.description is None
    assert job.apply_url == ("https://careers.swissre.test/talentcommunity/apply/101/?locale=en_GB")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_swiss_re_rejects_non_swiss_listing_result() -> None:
    parser = SwissReJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [101],
                    start=1,
                    end=1,
                    total=1,
                    country="DE",
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_swiss_re_rejects_listing_without_catalog_contract() -> None:
    parser = SwissReJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_swiss_re_enforces_catalog_page_limit() -> None:
    parser = SwissReJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_swiss_re_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["swiss_re"]
    assert isinstance(parser, SwissReJobsParser)
    assert parser.base_url == settings.swiss_re_jobs_base_url
    assert parser.search_url == settings.swiss_re_jobs_search_url
    assert parser.max_pages == settings.swiss_re_jobs_max_pages
    assert parser.max_catalog_passes == settings.swiss_re_jobs_max_catalog_passes
    assert parser.detail_workers == settings.swiss_re_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Swiss Re", "filters": {}},
            "sources": ["swiss_re", "swiss_re"],
        }
    )
    assert request.sources == ["swiss_re"]


def test_swiss_re_jobs_render_as_direct_company_imports() -> None:
    job = SwissReJobsParser().normalize_job(
        {
            "id": "1412388733",
            "title": "Senior Security Analyst",
            "location": "Zurich, Zurich, CH",
            "url": "https://careers.swissre.com/job/Zurich-Security-Analyst/1412388733/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="swiss_re-1412388733",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Swiss Re import"
    assert stored["id"] == "swiss_re-1412388733"
