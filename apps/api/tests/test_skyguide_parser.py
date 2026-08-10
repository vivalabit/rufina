from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.skyguide import SkyguideJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="/job/Wangen-Network-Architect-{job_id}/{job_id}/">
              Network Architect {job_id} (80-100%)
            </a>
          </td>
          <td class="colLocation">
            <span class="jobLocation">Wangen b. Dübendorf, CH</span>
          </td>
          <td class="colDepartment">
            <span class="jobDepartment">IT</span>
          </td>
          <td class="colDate">
            <span class="jobDate">Aug 5, 2026</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <span class="paginationLabel">
        Results <b>{start} – {end}</b> of <b>{total}</b>
      </span>
      <table id="searchresults"><tbody>{rows}</tbody></table>
    </body></html>
    """


def detail_html(job_id: int, *, title: str | None = None) -> str:
    job_title = title or f"Network Architect {job_id} (80-100%)"
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Wed Aug 05 02:00:00 UTC 2026">
        <meta itemprop="validThrough" content="Thu Dec 31 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="Skyguide">
        <span itemprop="jobLocation">
          <span itemprop="address">
            <meta itemprop="streetAddress" content="Wangen b. Dübendorf, CH">
          </span>
        </span>
        <span itemprop="title" data-careersite-propertyid="title">{job_title}</span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <style>.jobdescription {{ color: red; }}</style>
            <h2>Your mission</h2>
            <p>Shape a secure and resilient connectivity landscape.</p>
            <h2>Your tasks</h2>
            <ul><li>Define reusable network architecture.</li></ul>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_skyguide_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search":
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

    parser = SkyguideJobsParser(
        base_url="https://jobs.skyguide.test/search?locale=en_US",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Skyguide vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/search"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["locale"] == "en_US"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[0].url.params["sortDirection"] == "desc"
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "skyguide"
    assert first.title == "Network Architect 101 (80-100%)"
    assert first.company == "Skyguide"
    assert first.location == "Wangen b. Dübendorf, CH"
    assert first.url == ("https://jobs.skyguide.test/job/Wangen-Network-Architect-101/101/")
    assert first.apply_url == ("https://jobs.skyguide.test/talentcommunity/apply/101/?locale=en_US")
    assert first.posted_at == "2026-08-05"
    assert first.employment_type == "80-100%"
    assert first.description == (
        "Your mission\n\n"
        "Shape a secure and resilient connectivity landscape.\n\n"
        "Your tasks\n\n"
        "- Define reusable network architecture."
    )
    assert first.raw["department"] == "IT"
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["valid_through"] == "2026-12-31"


def test_skyguide_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/search":
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
        return httpx.Response(200, text=listing_html(ids, start=start, end=end, total=3))

    parser = SkyguideJobsParser(
        base_url="https://jobs.skyguide.test/search?locale=en_US",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_skyguide_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SkyguideJobsParser(
        base_url="https://jobs.skyguide.test/search?locale=en_US",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Network Architect 101 (80-100%)"
    assert job.location == "Wangen b. Dübendorf, CH"
    assert job.posted_at == "2026-08-05"
    assert job.description is None
    assert job.apply_url == ("https://jobs.skyguide.test/talentcommunity/apply/101/?locale=en_US")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_skyguide_rejects_duplicate_listing_ids() -> None:
    parser = SkyguideJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101, 101], start=1, end=2, total=2),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_skyguide_rejects_listing_without_catalog_contract() -> None:
    parser = SkyguideJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_skyguide_enforces_catalog_page_limit() -> None:
    parser = SkyguideJobsParser(
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


def test_skyguide_wraps_listing_request_failures() -> None:
    parser = SkyguideJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_skyguide_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["skyguide"]
    assert isinstance(parser, SkyguideJobsParser)
    assert parser.base_url == settings.skyguide_jobs_base_url
    assert parser.max_pages == settings.skyguide_jobs_max_pages
    assert parser.max_catalog_passes == settings.skyguide_jobs_max_catalog_passes
    assert parser.detail_workers == settings.skyguide_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Skyguide", "filters": {}},
            "sources": ["skyguide", "skyguide"],
        }
    )
    assert request.sources == ["skyguide"]


def test_skyguide_jobs_render_as_direct_company_imports() -> None:
    job = SkyguideJobsParser().normalize_job(
        {
            "id": "101",
            "title": "Network Architect (80-100%)",
            "location": "Wangen b. Dübendorf, CH",
            "url": "https://jobs.skyguide.ch/job/Wangen-Network-Architect/101/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="skyguide-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Skyguide import"
    assert stored["id"] == "skyguide-101"
    assert stored["company"] == "Skyguide"
