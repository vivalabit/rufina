from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.komax_group import (
    KomaxGroupJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = (
    "https://jobs.komaxgroup.test/search/?q=&locationsearch=switzerland&"
    "searchResultView=LIST&pageNumber=0&facetFilters=%7B%7D&sortBy=&"
    "markerViewed=&carouselIndex="
)
API_URL = "https://jobs.komaxgroup.test/services/recruiting/v1/jobs"


def search_html() -> str:
    return '<script>$.ajaxSetup({headers: {"X-CSRF-Token": "csrf-token"}});</script>'


def api_record(
    job_id: int,
    *,
    title: str | None = None,
    location: str = "Dierikon, CHE, 6036<br/>",
    city: str = "Dierikon",
    job_function: str = "Engineering",
    employment_type: str = "Fulltime",
    posted_at: str = "8/10/26",
) -> dict[str, object]:
    return {
        "response": {
            "id": str(job_id),
            "unifiedStandardTitle": title or f"Development Engineer {job_id}",
            "unifiedUrlTitle": f"Development-Engineer-{job_id}",
            "unifiedStandardStart": posted_at,
            "jobLocationShort": [location],
            "sfstd_jobLocation_obj": [city],
            "supportedLocales": ["en_US"],
            "JobFunction": [job_function],
            "filter1": [employment_type],
        }
    }


def api_payload(records: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {"jobSearchResult": records, "totalJobs": total}


def detail_html(
    job_id: int,
    *,
    title: str | None = None,
    city: str = "Dierikon",
    job_function: str = "Engineering",
    career_level: str = "Professionals",
    employment_type: str = "Fulltime",
    apply_job_id: int | None = None,
    canonical_url: str | None = None,
) -> str:
    job_title = title or f"Development Engineer {job_id}"
    canonical = canonical_url or (
        f"https://jobs.komaxgroup.test/job/Development-Engineer-{job_id}/"
        f"{job_id}-en_US/"
    )
    application_id = apply_job_id or job_id
    return f"""
    <html>
      <head><link rel="canonical" href="{canonical}"></head>
      <body>
        <div class="jobDisplayShell" itemscope
             itemtype="http://schema.org/JobPosting">
          <span itemprop="description"><p>&nbsp;</p></span>
          <span itemprop="title">{job_title}</span>
          <span itemprop="description">
            <p><strong>Your responsibilities</strong></p>
            <ul><li>Develop reliable automation systems.</li></ul>
            <p>Collaborate with an international engineering team.</p>
          </span>
          <a class="dialogApplyBtn"
             href="/talentcommunity/apply/{application_id}/?locale=en_US">
            Apply now
          </a>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Posting Location:&nbsp;</span>
            <span class="rtltextaligneligible">{city}</span>
          </div>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Professional area:&nbsp;</span>
            <span class="rtltextaligneligible">{job_function}</span>
          </div>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Career Level:&nbsp;</span>
            <span class="rtltextaligneligible">{career_level}</span>
          </div>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Employment Type:&nbsp;</span>
            <span class="rtltextaligneligible">{employment_type}</span>
          </div>
          <span itemprop="description"><p>Questions? Contact Komax Recruiting.</p></span>
        </div>
      </body>
    </html>
    """


def test_komax_group_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "POST":
            page_number = json.loads(request.content)["pageNumber"]
            records = (
                [api_record(2157), api_record(2217)]
                if page_number == 0
                else [
                    api_record(
                        2259,
                        title="Field Service Engineer 100% (w/m)",
                        job_function="Customer Service",
                    )
                ]
            )
            return httpx.Response(200, json=api_payload(records, total=3), request=request)
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
        return httpx.Response(
            200,
            text=detail_html(
                job_id,
                title=(
                    "Field Service Engineer 100% (w/m)"
                    if job_id == 2259
                    else f"Development Engineer {job_id}"
                ),
                job_function="Customer Service" if job_id == 2259 else "Engineering",
            ),
            request=request,
        )

    result = KomaxGroupJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Komax Group Switzerland vacancies from 3 catalog records "
        "across 2 page requests"
    )
    assert len(result.jobs) == 3
    listing_requests = [request for request in requests if request.method == "POST"]
    assert len(listing_requests) == 2
    assert listing_requests[0].headers["x-csrf-token"] == "csrf-token"
    assert json.loads(listing_requests[0].content) == {
        "locale": "en_US",
        "pageNumber": 0,
        "sortBy": "",
        "keywords": "",
        "location": "switzerland",
        "facetFilters": {},
        "brand": "",
        "skills": [],
        "categoryId": 0,
        "alertId": "",
        "rcmCandidateId": "",
    }

    job = result.jobs[0]
    assert job.source == "komax_group"
    assert job.title == "Development Engineer 2157"
    assert job.company == "Komax Group"
    assert job.location == "Dierikon, CHE, 6036"
    assert job.url == (
        "https://jobs.komaxgroup.test/job/Development-Engineer-2157/2157-en_US/"
    )
    assert job.apply_url == (
        "https://jobs.komaxgroup.test/talentcommunity/apply/2157/?locale=en_US"
    )
    assert job.posted_at == "2026-08-10"
    assert job.employment_type == "Fulltime"
    assert job.seniority == "Professionals"
    assert job.description == (
        "Your responsibilities\n\n"
        "- Develop reliable automation systems.\n\n"
        "Collaborate with an international engineering team.\n\n"
        "Questions? Contact Komax Recruiting."
    )
    assert job.raw["job_function"] == "Engineering"
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3


def test_komax_group_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "GET":
            job_id = int(
                request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0]
            )
            return httpx.Response(200, text=detail_html(job_id), request=request)
        page_number = json.loads(request.content)["pageNumber"]
        if page_number == 0:
            first_page_calls += 1
            records = [api_record(2157), api_record(2217)]
        else:
            records = [api_record(2217 if first_page_calls == 1 else 2259)]
        return httpx.Response(200, json=api_payload(records, total=3), request=request)

    result = KomaxGroupJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_komax_group_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json=api_payload([api_record(2157)], total=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        KomaxGroupJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Development Engineer 2157"
    assert job.location == "Dierikon, CHE, 6036"
    assert job.apply_url == (
        "https://jobs.komaxgroup.test/talentcommunity/apply/2157/?locale=en_US"
    )
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_komax_group_rejects_duplicate_or_non_swiss_catalog_records() -> None:
    def parser_for(records: list[dict[str, object]]) -> KomaxGroupJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, text=search_html(), request=request)
            return httpx.Response(
                200,
                json=api_payload(records, total=len(records)),
                request=request,
            )

        return KomaxGroupJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([api_record(2157), api_record(2157)]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parser_for(
            [api_record(2157, location="Aachen, DEU, 52062", city="Aachen")]
        ).search(LinkedInSearchRequest())


def test_komax_group_rejects_malformed_catalog_and_mismatched_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html(), request=request)
        return httpx.Response(200, json={"totalJobs": 1}, request=request)

    parser = KomaxGroupJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        parser.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(2157, apply_job_id=999),
            page_url=(
                "https://jobs.komaxgroup.test/job/Development-Engineer-2157/"
                "2157-en_US/"
            ),
            expected_url=(
                "https://jobs.komaxgroup.test/job/Development-Engineer-2157/"
                "2157-en_US/"
            ),
            expected_job_id="2157",
            expected_title="Development Engineer 2157",
            expected_cities=["Dierikon"],
            expected_job_function="Engineering",
            expected_employment_type="Fulltime",
        )


def test_komax_group_rejects_missing_csrf_token() -> None:
    parser = KomaxGroupJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>Jobs</html>", request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="CSRF token"):
        parser.search(LinkedInSearchRequest())


def test_komax_group_enforces_catalog_page_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html(), request=request)
        return httpx.Response(
            200,
            json=api_payload([api_record(2157), api_record(2217)], total=3),
            request=request,
        )

    parser = KomaxGroupJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        max_pages=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_komax_group_wraps_listing_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html(), request=request)
        return httpx.Response(503, request=request)

    parser = KomaxGroupJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_komax_group_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["komax_group"]
    assert isinstance(parser, KomaxGroupJobsParser)
    assert parser.base_url == settings.komax_group_jobs_base_url
    assert parser.api_url == settings.komax_group_jobs_api_url
    assert parser.max_pages == settings.komax_group_jobs_max_pages
    assert parser.max_catalog_passes == settings.komax_group_jobs_max_catalog_passes
    assert parser.detail_workers == settings.komax_group_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Komax Group", "filters": {}},
            "sources": ["komax_group", "komax_group"],
        }
    )
    assert request.sources == ["komax_group"]


def test_komax_group_jobs_render_as_direct_company_imports() -> None:
    job = KomaxGroupJobsParser().normalize_job(
        {
            "id": "2157",
            "title": "Development Engineer Electronics",
            "location": "Dierikon, CHE, 6036",
            "posted_at": "2026-08-10",
            "employment_type": "Fulltime",
            "url": (
                "https://jobs.komaxgroup.com/job/Development-Engineer-Electronics/"
                "2157-en_US/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="komax_group-2157",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Komax Group import"
    assert stored["id"] == "komax_group-2157"
    assert stored["company"] == "Komax Group"
