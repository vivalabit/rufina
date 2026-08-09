from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.google import GoogleJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(job_id: int, *, location: str = "Zürich, Switzerland") -> str:
    return f"""
    <div class="sMn82b">
      <h3 class="QJPWVe">Software Engineer {job_id}</h3>
      <div class="op1BBf">
        <span class="RP7SMd"><i>corporate_fare</i><span>Google</span></span>
        <span class="r0wTof">{location}</span>
        <span class="wVSTAb">Mid</span>
      </div>
      <div class="Xsxa1e">
        <h4>Minimum qualifications</h4>
        <ul><li>Experience building reliable systems.</li></ul>
      </div>
      <a href="jobs/results/{job_id}-software-engineer-{job_id}"
         aria-label="Learn more about Software Engineer {job_id}"></a>
    </div>
    """


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Zürich, Switzerland",
) -> str:
    cards = "".join(listing_card(job_id, location=location) for job_id in ids)
    return f"""
    <html>
      <head><base href="https://www.google.test/about/careers/applications/"></head>
      <body>
        <h1>Jobs search results</h1>
        <p>{total} jobs matched</p>
        {cards}
        <p>Showing {start} to {end} of {total} rows</p>
      </body>
    </html>
    """


def detail_html(job_id: int) -> str:
    return f"""
    <html>
      <head><base href="https://www.google.test/about/careers/applications/"></head>
      <body>
        <div class="DkhPwc" data-id="{job_id}">
          <h2 class="p1N2lc">Software Engineer {job_id}</h2>
          <div class="op1BBf">
            <span class="RP7SMd"><i>corporate_fare</i><span>Google</span></span>
            <span class="r0wTof">Zürich, Switzerland</span>
            <span class="wVSTAb">Mid</span>
          </div>
          <a id="apply-action-button"
             href="./apply?jobId=encrypted-{job_id}&amp;loc=CH">Apply</a>
          <div class="KwJkGe">
            <h3>Minimum qualifications:</h3>
            <ul><li>Build reliable services.</li></ul>
            <h3>Preferred qualifications:</h3>
            <ul><li>Experience with distributed systems.</li></ul>
          </div>
          <div class="aG5W3">
            <h3>About the job</h3>
            <p>Develop products used around the world.</p>
          </div>
          <div class="BDNOWe">
            <h3>Responsibilities</h3>
            <ul><li>Design and review production systems.</li></ul>
          </div>
        </div>
      </body>
    </html>
    """


def test_google_scans_full_catalog_and_enriches_records() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/jobs/results/"):
            page = int(request.url.params.get("page", "1"))
            if page == 1:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
            )
        job_id = int(request.url.path.split("/")[-1].split("-", maxsplit=1)[0])
        return httpx.Response(200, text=detail_html(job_id))

    parser = GoogleJobsParser(
        base_url=(
            "https://www.google.test/about/careers/applications/jobs/results/"
            "?location=Zurich%2C%20Switzerland"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Google Zürich vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [
        request for request in requests if request.url.path.endswith("/jobs/results/")
    ]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["location"] == "Zurich, Switzerland"
    assert "page" not in listing_requests[0].url.params
    assert listing_requests[1].url.params["page"] == "2"
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "google"
    assert first.title == "Software Engineer 101"
    assert first.company == "Google"
    assert first.location == "Zürich, Switzerland"
    assert first.url == (
        "https://www.google.test/about/careers/applications/jobs/results/101-software-engineer-101"
    )
    assert first.apply_url == (
        "https://www.google.test/about/careers/applications/apply?jobId=encrypted-101&loc=CH"
    )
    assert first.seniority == "Mid"
    assert first.description == (
        "Minimum qualifications:\n\n- Build reliable services.\n\n"
        "Preferred qualifications:\n\n- Experience with distributed systems.\n\n"
        "About the job\n\nDevelop products used around the world.\n\n"
        "Responsibilities\n\n- Design and review production systems."
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 3


def test_google_retries_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if not request.url.path.endswith("/jobs/results/"):
            job_id = int(request.url.path.split("/")[-1].split("-", maxsplit=1)[0])
            return httpx.Response(200, text=detail_html(job_id))

        page = int(request.url.params.get("page", "1"))
        if page == 1:
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

    parser = GoogleJobsParser(
        max_catalog_passes=2,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_google_expands_hidden_multi_location_roles() -> None:
    page_html = (
        detail_html(101)
        .replace(
            '<span class="r0wTof">Zürich, Switzerland</span>',
            '<span class="r0wTof">Mountain View, CA, USA</span>',
        )
        .replace(
            '<div class="KwJkGe">',
            '<div class="KwJkGe"><p>Preferred working locations: '
            "<b>Mountain View, CA, USA; New York, NY, USA; Zürich, Switzerland</b>"
            "</p>",
        )
    )

    detail = parse_detail_html(
        page_html,
        page_url=(
            "https://www.google.test/about/careers/applications/jobs/results/101-software-engineer"
        ),
        expected_job_id="101",
    )

    assert detail["location"] == ("Mountain View, CA, USA; New York, NY, USA; Zürich, Switzerland")


def test_google_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs/results/"):
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = GoogleJobsParser(transport=httpx.MockTransport(handler))

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Software Engineer 101"
    assert job.company == "Google"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description == ("Minimum qualifications\n\n- Experience building reliable systems.")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_google_rejects_listing_without_catalog_contract_or_complete_record() -> None:
    missing_contract = GoogleJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )
    incomplete = GoogleJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1).replace(
                    '<h3 class="QJPWVe">Software Engineer 101</h3>',
                    '<h3 class="QJPWVe"></h3>',
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="result range"):
        missing_contract.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        incomplete.search(LinkedInSearchRequest())


def test_google_enforces_catalog_page_limit() -> None:
    parser = GoogleJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_google_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["google"]
    assert isinstance(parser, GoogleJobsParser)
    assert parser.base_url == settings.google_jobs_base_url
    assert parser.max_pages == settings.google_jobs_max_pages
    assert parser.max_catalog_passes == settings.google_jobs_max_catalog_passes
    assert parser.detail_workers == settings.google_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Google", "filters": {}},
            "sources": ["google", "google"],
        }
    )
    assert request.sources == ["google"]


def test_google_jobs_render_as_direct_company_imports() -> None:
    parser = GoogleJobsParser()
    job = parser.normalize_job(
        {
            "id": "101",
            "title": "Software Engineer",
            "company": "Google",
            "location": "Zürich, Switzerland",
            "url": (
                "https://www.google.com/about/careers/applications/jobs/"
                "results/101-software-engineer"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="google-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Google import"
    assert stored["id"] == "google-101"
