from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.nestle_switzerland import (
    NestleSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://jobdetails.nestle.test/search/"


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Konolfingen, CH",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="/job/Konolfingen-Anlagenfuehrer-Produktion/{job_id}/">
              Anlagenführer:in Produktion {job_id} 100%
            </a>
          </td>
          <td class="colFacility"><span class="jobFacility"></span></td>
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
    company: str = "Nestle Operational Services Worldwide SA",
    location: str = "Konolfingen, CH",
) -> str:
    job_title = title or f"Anlagenführer:in Produktion {job_id} 100%"
    return f"""
    <html><head>
      <meta property="og:title" content="{job_title}">
    </head><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <span itemprop="jobLocation"><span itemprop="address">
          <meta itemprop="streetAddress" content="{location}">
        </span></span>
        <meta itemprop="datePosted" content="Sat Aug 15 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{company}">
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Join Nestlé and help us elevate our world.</p>
            <h1><span>{job_title}</span></h1>
            <div id="jobcontent">
              <h4>We Elevate... Your Responsibilities</h4>
              <ul><li>Support the application portfolio.</li></ul>
            </div>
          </span>
        </span>
        <span class="jobGeoLocation">{location}</span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_nestle_scans_full_swiss_catalog_and_enriches_every_record() -> None:
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

    result = NestleSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 Nestlé Switzerland vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["locale"] == "en_US"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[1].url.params["startrow"] == "2"

    job = result.jobs[0]
    assert job.source == "nestle_switzerland"
    assert job.title == "Anlagenführer:in Produktion 101 100%"
    assert job.company == "Nestlé"
    assert job.location == "Konolfingen, CH"
    assert job.url == (
        "https://jobdetails.nestle.test/job/Konolfingen-Anlagenfuehrer-Produktion/101/"
    )
    assert job.apply_url == (
        "https://jobdetails.nestle.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert job.posted_at == "2026-08-15"
    assert job.employment_type == "100%"
    assert job.description == (
        "Join Nestlé and help us elevate our world.\n\n"
        "Anlagenführer:in Produktion 101 100%\n\n"
        "We Elevate... Your Responsibilities\n\n"
        "- Support the application portfolio."
    )
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["legal_company"] == ("Nestle Operational Services Worldwide SA")


def test_nestle_retries_shifted_pages_until_all_ids_are_seen() -> None:
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

    result = NestleSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_nestle_preserves_listing_when_detail_contract_fails() -> None:
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
        NestleSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Anlagenführer:in Produktion 101 100%"
    assert job.location == "Konolfingen, CH"
    assert job.description is None
    assert job.posted_at == "2026-08-15"
    assert job.apply_url == (
        "https://jobdetails.nestle.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert "incomplete or non-Swiss vacancy" in str(job.raw["detail_error"])


def test_nestle_accepts_legal_entity_without_accent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(101),
            request=request,
        )

    job = (
        NestleSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description
    assert "Anlagenführer:in Produktion 101" in job.description
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
def test_nestle_rejects_invalid_catalogs(page_html: str, message: str) -> None:
    parser = NestleSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page_html, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_nestle_enforces_page_limit_and_wraps_http_errors() -> None:
    too_large = NestleSwitzerlandJobsParser(
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

    unavailable = NestleSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_nestle_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["nestle_switzerland"]
    assert isinstance(parser, NestleSwitzerlandJobsParser)
    assert parser.base_url == settings.nestle_switzerland_jobs_base_url
    assert parser.max_pages == settings.nestle_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.nestle_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.nestle_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Nestlé", "filters": {}},
            "sources": ["nestle_switzerland", "nestle_switzerland"],
        }
    )
    assert request.sources == ["nestle_switzerland"]


def test_nestle_jobs_render_as_direct_company_imports() -> None:
    job = NestleSwitzerlandJobsParser().normalize_job(
        {
            "id": "1416306233",
            "title": "Anlagenführer:in Produktion 100%",
            "location": "Konolfingen, CH",
            "url": ("https://jobdetails.nestle.com/job/Konolfingen-Anlagenfuehrer/1416306233/"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="nestle_switzerland-1416306233",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Nestlé Switzerland import"
    assert stored["company"] == "Nestlé"
    assert stored["id"] == "nestle_switzerland-1416306233"
