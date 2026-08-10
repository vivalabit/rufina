from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.ao_foundation import AoFoundationJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_tiles(ids: list[int]) -> str:
    return "".join(
        f"""
        <li class="job-tile job-id-{job_id}"
            data-url="/job/Davos-Platz-Cloud-Engineer-{job_id}/{job_id}/">
          <div class="tiletitle">
            <a class="jobTitle-link"
               href="/job/Davos-Platz-Cloud-Engineer-{job_id}/{job_id}/">
              Cloud Engineer {job_id}
            </a>
          </div>
        </li>
        """
        for job_id in ids
    )


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    page_size: int = 2,
) -> str:
    return f"""
    <html><body>
      <span id="tile-search-results-label">
        Showing {start} to {end} of {total} Jobs
      </span>
      <ul id="job-tile-list" data-per-page="{page_size}">
        {listing_tiles(ids)}
      </ul>
    </body></html>
    """


def detail_html(job_id: int, *, title: str | None = None) -> str:
    job_title = title or f"Cloud Engineer {job_id}"
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Tue Jul 28 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="AO Foundation">
        <span itemprop="jobLocation">
          <span itemprop="address">
            <meta itemprop="streetAddress" content="Davos Platz, CH">
          </span>
        </span>
        <span itemprop="title" data-careersite-propertyid="title">{job_title}</span>
        <span data-careersite-propertyid="shifttype">Permanent</span>
        <span data-careersite-propertyid="customfield5">80 - 100%</span>
        <span data-careersite-propertyid="location">
          <span class="jobGeoLocation">Davos Platz, CH</span>
        </span>
        <span data-careersite-propertyid="customfield1">Experienced professional</span>
        <span data-careersite-propertyid="customfield2">English or German</span>
        <span data-careersite-propertyid="date">Jul 28, 2026</span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <h2>Short Description</h2>
            <p>Build secure research platforms.</p>
            <ul><li>Partner with international teams.</li></ul>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_ao_foundation_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/locale=en_US":
            return httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        if request.url.path == "/tile-search-results/":
            return httpx.Response(200, text=listing_tiles([103]))
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = AoFoundationJobsParser(
        base_url="https://careers.aofoundation.test/search/locale=en_US",
        page_url="https://careers.aofoundation.test/tile-search-results/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 AO Foundation vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [
        request
        for request in requests
        if request.url.path in {"/search/locale=en_US", "/tile-search-results/"}
    ]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["q"] == ""
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[0].url.params["sortDirection"] == "desc"
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "ao_foundation"
    assert first.title == "Cloud Engineer 101"
    assert first.company == "AO Foundation"
    assert first.location == "Davos Platz, CH"
    assert first.url == (
        "https://careers.aofoundation.test/job/Davos-Platz-Cloud-Engineer-101/101/"
    )
    assert first.apply_url == (
        "https://careers.aofoundation.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert first.posted_at == "2026-07-28"
    assert first.employment_type == "Permanent · 80 - 100%"
    assert first.seniority == "Experienced professional"
    assert first.description == (
        "Short Description\n\n"
        "Build secure research platforms.\n\n"
        "- Partner with international teams."
    )
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["language"] == "English or German"


def test_ao_foundation_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path == "/search/locale=en_US":
            first_page_calls += 1
            return httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        if request.url.path == "/tile-search-results/":
            ids = [102] if first_page_calls == 1 else [103]
            return httpx.Response(200, text=listing_tiles(ids))
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = AoFoundationJobsParser(
        base_url="https://careers.aofoundation.test/search/locale=en_US",
        page_url="https://careers.aofoundation.test/tile-search-results/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_ao_foundation_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/locale=en_US":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = AoFoundationJobsParser(
        base_url="https://careers.aofoundation.test/search/locale=en_US",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Cloud Engineer 101"
    assert job.location is None
    assert job.description is None
    assert job.apply_url == (
        "https://careers.aofoundation.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ao_foundation_rejects_listing_without_catalog_contract() -> None:
    parser = AoFoundationJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_ao_foundation_enforces_catalog_page_limit() -> None:
    parser = AoFoundationJobsParser(
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


def test_ao_foundation_rejects_truncated_additional_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/locale=en_US":
            return httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=4),
            )
        return httpx.Response(200, text=listing_tiles([103]))

    parser = AoFoundationJobsParser(
        base_url="https://careers.aofoundation.test/search/locale=en_US",
        page_url="https://careers.aofoundation.test/tile-search-results/",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="expected to contain 2"):
        parser.search(LinkedInSearchRequest())


def test_ao_foundation_wraps_listing_request_failures() -> None:
    parser = AoFoundationJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_ao_foundation_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ao_foundation"]
    assert isinstance(parser, AoFoundationJobsParser)
    assert parser.base_url == settings.ao_foundation_jobs_base_url
    assert parser.page_url == settings.ao_foundation_jobs_page_url
    assert parser.max_pages == settings.ao_foundation_jobs_max_pages
    assert parser.max_catalog_passes == settings.ao_foundation_jobs_max_catalog_passes
    assert parser.detail_workers == settings.ao_foundation_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AO Foundation", "filters": {}},
            "sources": ["ao_foundation", "ao_foundation"],
        }
    )
    assert request.sources == ["ao_foundation"]


def test_ao_foundation_jobs_render_as_direct_company_imports() -> None:
    job = AoFoundationJobsParser().normalize_job(
        {
            "id": "101",
            "title": "Cloud Engineer",
            "url": "https://careers.aofoundation.org/job/Cloud-Engineer/101/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="ao_foundation-101",
        added_at=datetime.now(UTC),
    )

    assert stored["id"] == "ao_foundation-101"
    assert stored["logo"] == "company"
    assert stored["department"] == "AO Foundation import"
    assert stored["company"] == "AO Foundation"
