from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.ey_switzerland import (
    EySwitzerlandJobsParser,
)
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
               href="/ey/job/Zurich-Technology-Consultant-8005/{job_id}/">
              Technology Consultant {job_id}
            </a>
          </td>
          <td class="colLocation">
            <span class="jobLocation">Zurich, CH, 8005</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <table id="searchresults"><tbody>{rows}</tbody></table>
      <span class="paginationLabel">Results <b>{start} – {end}</b> of <b>{total}</b></span>
    </body></html>
    """


def detail_html(job_id: int, *, title: str | None = None) -> str:
    job_title = title or f"Technology Consultant {job_id} (80-100%)"
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Sat Aug 08 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="EY">
        <span data-careersite-propertyid="title">{job_title}</span>
        <span data-careersite-propertyid="city">Zurich</span>
        <span data-careersite-propertyid="customfield3">Primary Location Only</span>
        <span data-careersite-propertyid="date">Aug 8, 2026</span>
        <span data-careersite-propertyid="customfield5">REQ-{job_id}</span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Build a better working world.</p>
            <h3>Your key responsibilities</h3>
            <ul><li>Advise clients.</li><li>Work with the team.</li></ul>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_ey_switzerland_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/ey/search/":
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

    parser = EySwitzerlandJobsParser(
        base_url=("https://careers.ey.test/ey/search/?optionsFacetsDD_country=CH"),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 EY Switzerland vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/ey/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["optionsFacetsDD_country"] == "CH"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "ey_switzerland"
    assert first.title == "Technology Consultant 101 (80-100%)"
    assert first.company == "EY"
    assert first.location == "Zurich"
    assert first.url == "https://careers.ey.test/ey/job/Zurich-Technology-Consultant-8005/101/"
    assert first.apply_url == ("https://careers.ey.test/talentcommunity/apply/101/?locale=en_US")
    assert first.posted_at == "2026-08-08"
    assert first.employment_type == "80-100%"
    assert first.description == (
        "Build a better working world.\n\n"
        "Your key responsibilities\n\n"
        "- Advise clients.\n"
        "- Work with the team."
    )
    assert first.raw["id"] == "101"
    assert first.raw["detail"]["requisition_id"] == "REQ-101"


def test_ey_switzerland_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/ey/search/":
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

    parser = EySwitzerlandJobsParser(
        base_url="https://careers.ey.test/ey/search/?optionsFacetsDD_country=CH",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_ey_switzerland_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ey/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = EySwitzerlandJobsParser(
        base_url="https://careers.ey.test/ey/search/?optionsFacetsDD_country=CH",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Technology Consultant 101"
    assert job.location == "Zurich, CH, 8005"
    assert job.description is None
    assert job.apply_url == ("https://careers.ey.test/talentcommunity/apply/101/?locale=en_US")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ey_switzerland_rejects_listing_without_catalog_contract() -> None:
    parser = EySwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_ey_switzerland_enforces_catalog_page_limit() -> None:
    parser = EySwitzerlandJobsParser(
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


def test_ey_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ey_switzerland"]
    assert isinstance(parser, EySwitzerlandJobsParser)
    assert parser.base_url == settings.ey_switzerland_jobs_base_url
    assert parser.max_pages == settings.ey_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.ey_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.ey_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "EY Switzerland", "filters": {}},
            "sources": ["ey_switzerland", "ey_switzerland"],
        }
    )
    assert request.sources == ["ey_switzerland"]


def test_ey_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = EySwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "101",
            "title": "Technology Consultant",
            "location": "Zurich, CH, 8005",
            "url": "https://careers.ey.com/ey/job/Zurich-Technology-Consultant/101/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="ey_switzerland-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "EY Switzerland import"
    assert stored["id"] == "ey_switzerland-101"
