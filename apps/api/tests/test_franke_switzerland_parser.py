from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.franke_switzerland import (
    FrankeSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://jobs.franke.test/search/"


def job_url(job_id: int, *, brand: str | None = None) -> str:
    prefix = f"/{brand}" if brand else ""
    return (
        f"https://jobs.franke.test{prefix}/job/Aarburg-Test-Engineer-100-Hybrid/"
        f"{job_id}/"
    )


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Aarburg, CH",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="{'/Wesco' if job_id == 103 else ''}/job/Aarburg-Test-Engineer-100-Hybrid/{job_id}/">
              Test Engineer {job_id} (w/m) 80-100% - Hybrid
            </a>
          </td>
          <td class="colDate"><span class="jobDate">Aug 21, 2026</span></td>
          <td class="colLocation"><span class="jobLocation">{location}</span></td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><head><title>Switzerland - franke Jobs</title></head><body>
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
    company: str = "franke",
    location: str = "Aarburg, CH",
    canonical_id: int | None = None,
    brand: str | None = None,
) -> str:
    job_title = title or f"Test Engineer {job_id} (w/m) 80-100% - Hybrid"
    canonical = job_url(canonical_id or job_id, brand=brand)
    return f"""
    <html><head>
      <link rel="canonical" href="{canonical}">
      <meta property="og:title" content="{job_title}">
      <meta property="og:site_name" content="Franke Jobs">
    </head><body>
      <div class="jobDisplayShell" itemscope
           itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Fri Aug 21 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{company}">
        <h1 id="job-title" itemprop="title">{job_title}</h1>
        <p id="job-location"><span class="jobGeoLocation">{location}</span></p>
        <span itemprop="description" class="jobdescription">
          <h2>About Franke</h2>
          <p>Build reliable coffee-system applications.</p>
          <h2>Your responsibilities</h2>
          <ul><li>Own automated product tests.</li></ul>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=de_DE">Apply now</a>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=de_DE">Apply now</a>
      </div>
    </body></html>
    """


def test_franke_scans_full_swiss_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["locationsearch"] == "switzerland"
            assert request.url.params["locale"] == "en_US"
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
        return httpx.Response(
            200,
            text=detail_html(job_id, brand="Wesco" if job_id == 103 else None),
            request=request,
        )

    result = FrankeSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Franke Switzerland vacancies from 3 catalog records "
        "across 2 page requests"
    )
    assert len(result.jobs) == 3
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[1].url.params["startrow"] == "2"

    job = result.jobs[0]
    assert job.source == "franke_switzerland"
    assert job.title == "Test Engineer 101 (w/m) 80-100% - Hybrid"
    assert job.company == "Franke Group"
    assert job.location == "Aarburg, CH"
    assert job.url == job_url(101)
    assert job.apply_url == (
        "https://jobs.franke.test/talentcommunity/apply/101/?locale=de_DE"
    )
    assert job.posted_at == "2026-08-21"
    assert job.employment_type == "80–100%"
    assert job.description == (
        "About Franke\n\nBuild reliable coffee-system applications.\n\n"
        "Your responsibilities\n\n- Own automated product tests."
    )
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["legal_company"] == "franke"
    assert result.jobs[2].url == job_url(103, brand="Wesco")


def test_franke_retries_shifted_pages_until_all_ids_are_seen() -> None:
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
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(
            200,
            text=detail_html(job_id, brand="Wesco" if job_id == 103 else None),
            request=request,
        )

    result = FrankeSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_franke_preserves_listing_when_detail_contract_fails() -> None:
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
        FrankeSwitzerlandJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Test Engineer 101 (w/m) 80-100% - Hybrid"
    assert job.location == "Aarburg, CH"
    assert job.description is None
    assert job.posted_at == "2026-08-21"
    assert job.apply_url == (
        "https://jobs.franke.test/talentcommunity/apply/101/?locale=en_US"
    )
    assert "incomplete or non-Swiss vacancy" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (
            listing_html([101], start=1, end=1, total=1, location="Berlin, DE"),
            "non-Swiss vacancy",
        ),
        ("<html><body>Jobs</body></html>", "search results"),
        (listing_html([101, 101], start=1, end=2, total=2), "duplicate vacancy IDs"),
    ],
)
def test_franke_rejects_invalid_catalogs(page_html: str, message: str) -> None:
    parser = FrankeSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page_html, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_franke_accepts_explicit_empty_catalog() -> None:
    result = FrankeSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([], start=1, end=0, total=0),
                request=request,
            )
        )
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Franke Switzerland vacancies from 0 catalog records "
        "across 1 page request"
    )


def test_franke_enforces_page_limit_and_wraps_http_errors() -> None:
    too_large = FrankeSwitzerlandJobsParser(
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

    unavailable = FrankeSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_franke_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["franke_switzerland"]
    assert isinstance(parser, FrankeSwitzerlandJobsParser)
    assert parser.base_url == settings.franke_switzerland_jobs_base_url
    assert parser.max_pages == settings.franke_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.franke_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == settings.franke_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Franke", "filters": {}},
            "sources": ["franke_switzerland", "franke_switzerland"],
        }
    )
    assert request.sources == ["franke_switzerland"]


def test_franke_jobs_render_as_direct_company_imports() -> None:
    job = FrankeSwitzerlandJobsParser().normalize_job(
        {
            "id": "1428534833",
            "title": "CX-Solution Project Manager (w/m) 100% - Hybrid",
            "location": "Aarburg, CH",
            "url": (
                "https://jobs.franke.com/job/Aarburg-CX-Solution-Project-Manager/"
                "1428534833/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="franke_switzerland-1428534833",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Franke Switzerland import"
    assert stored["company"] == "Franke Group"
    assert stored["id"] == "franke_switzerland-1428534833"
