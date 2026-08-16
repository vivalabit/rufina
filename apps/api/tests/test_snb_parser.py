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
from app.services.parsers.companies.snb import (
    SnbJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://careers.snb.test/search/?locale=de_DE"
API_URL = "https://careers.snb.test/services/recruiting/v1/jobs"


def search_html(*, csrf_token: str = "csrf-token") -> str:
    return f"""
    <html>
      <head><link rel="canonical" href="https://careers.snb.test/search/"></head>
      <body>
        <script>$.ajaxSetup({{headers: {{"X-CSRF-Token": "{csrf_token}"}}}});</script>
      </body>
    </html>
    """


def api_record(
    job_id: int,
    *,
    title: str | None = None,
    location: str = "Zürich, Schweiz ",
    work_model: str = "hybrid",
    employment_type: str = "Festanstellung",
    posted_at: str = "12.06.26",
) -> dict[str, object]:
    return {
        "response": {
            "id": str(job_id),
            "unifiedStandardTitle": title or f"Data Platform Engineer {job_id}",
            "unifiedUrlTitle": f"Data-Platform-Engineer-{job_id}",
            "unifiedStandardStart": posted_at,
            "jobLocationShort": [location],
            "supportedLocales": ["de_DE"],
            "cust_arbeitsform": [work_model],
            "cust_vertragsart": [employment_type],
        }
    }


def api_payload(records: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {"jobSearchResult": records, "totalJobs": total}


def detail_html(
    job_id: int,
    *,
    title: str | None = None,
    city: str = "Zürich",
    workload: str | None = "80% - 100%",
    work_model: str = "hybrid",
    employment_type: str = "Festanstellung",
    apply_job_id: int | None = None,
    canonical_url: str | None = None,
) -> str:
    job_title = title or f"Data Platform Engineer {job_id}"
    canonical = canonical_url or (
        f"https://careers.snb.test/job/Data-Platform-Engineer-{job_id}/{job_id}-de_DE/"
    )
    application_id = apply_job_id or job_id
    workload_text = f" ({workload})" if workload else ""
    return f"""
    <html>
      <head>
        <title>{job_title} Stellendetails | Schweizerische Nationalbank</title>
        <meta property="og:title" content="{job_title}">
        <link rel="canonical" href="{canonical}">
      </head>
      <body>
        <div class="joblayouttoken">
          <span class="rtltextaligneligible">
            <style>.hidden {{ display: none; }}</style>
            <p><strong>{job_title}{workload_text}</strong></p>
            <p>{city} / {employment_type} / {work_model}</p>
            <p>Gestalten Sie zuverlässige Plattformen für die Nationalbank.</p>
          </span>
        </div>
        <div class="joblayouttoken">
          <span class="rtltextaligneligible">
            <h2>Ihre Aufgaben</h2>
            <ul><li>Automatisieren Sie zentrale Datendienste.</li></ul>
            <h2>Ihr Profil</h2><p>Sie arbeiten strukturiert und sorgfältig.</p>
          </span>
        </div>
        <div class="joblayouttoken">
          <span class="rtltextaligneligible">
            <h2>Unser Angebot</h2><p>Ein einzigartiges Arbeitsumfeld.</p>
          </span>
        </div>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{application_id}/?locale=de_DE">
          Jetzt bewerben
        </a>
      </body>
    </html>
    """


def test_snb_scans_complete_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "POST":
            page_number = json.loads(request.content)["pageNumber"]
            records = (
                [api_record(3453), api_record(3535)] if page_number == 0 else [api_record(3540)]
            )
            return httpx.Response(
                200,
                json=api_payload(records, total=3),
                request=request,
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
        return httpx.Response(200, text=detail_html(job_id), request=request)

    result = SnbJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 SNB Switzerland vacancies from 3 global catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.method == "POST"]
    assert len(listing_requests) == 2
    assert listing_requests[0].headers["x-csrf-token"] == "csrf-token"
    assert json.loads(listing_requests[0].content) == {
        "locale": "de_DE",
        "pageNumber": 0,
        "sortBy": "referencedate",
        "keywords": "",
        "location": "",
        "facetFilters": {},
        "brand": "",
        "skills": [],
        "categoryId": 0,
        "alertId": "",
        "rcmCandidateId": "",
    }

    job = result.jobs[0]
    assert job.source == "snb"
    assert job.title == "Data Platform Engineer 3453"
    assert job.company == "Schweizerische Nationalbank"
    assert job.location == "Zürich, Schweiz"
    assert job.url == ("https://careers.snb.test/job/Data-Platform-Engineer-3453/3453-de_DE/")
    assert job.apply_url == ("https://careers.snb.test/talentcommunity/apply/3453/?locale=de_DE")
    assert job.posted_at == "2026-06-12"
    assert job.employment_type == "80% - 100%, Festanstellung, hybrid"
    assert job.description == (
        "Data Platform Engineer 3453 (80% - 100%)\n"
        "Zürich / Festanstellung / hybrid\n"
        "Gestalten Sie zuverlässige Plattformen für die Nationalbank.\n"
        "Ihre Aufgaben\n- Automatisieren Sie zentrale Datendienste.\n"
        "Ihr Profil\nSie arbeiten strukturiert und sorgfältig.\n"
        "Unser Angebot\nEin einzigartiges Arbeitsumfeld."
    )
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3


def test_snb_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "GET":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
            return httpx.Response(200, text=detail_html(job_id), request=request)
        page_number = json.loads(request.content)["pageNumber"]
        if page_number == 0:
            first_page_calls += 1
            records = [api_record(3453), api_record(3535)]
        else:
            records = [api_record(3535 if first_page_calls == 1 else 3540)]
        return httpx.Response(200, json=api_payload(records, total=3), request=request)

    result = SnbJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_snb_filters_foreign_records_without_fetching_their_details() -> None:
    detail_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json=api_payload(
                    [api_record(3453), api_record(9000, location="Singapore, Singapur")],
                    total=2,
                ),
                request=request,
            )
        job_id = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0]
        detail_ids.append(job_id)
        return httpx.Response(200, text=detail_html(int(job_id)), request=request)

    result = SnbJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["Data Platform Engineer 3453"]
    assert detail_ids == ["3453"]
    assert "from 2 global catalog records" in str(result.message)


def test_snb_supports_apprenticeship_without_workload() -> None:
    url = "https://careers.snb.test/job/Data-Platform-Engineer-3453/3453-de_DE/"
    detail = parse_detail_html(
        detail_html(
            3453,
            workload=None,
            employment_type="Lehrstelle",
            work_model="vor Ort",
        ),
        page_url=url,
        expected_url=url,
        expected_job_id="3453",
        expected_title="Data Platform Engineer 3453",
        expected_cities=["Zürich"],
        expected_employment_type="Lehrstelle",
        expected_work_model="vor Ort",
    )

    assert detail["workload"] is None
    assert ".hidden" not in str(detail["description"])


def test_snb_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html(), request=request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json=api_payload([api_record(3453)], total=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        SnbJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Data Platform Engineer 3453"
    assert job.employment_type == "Festanstellung, hybrid"
    assert job.apply_url == ("https://careers.snb.test/talentcommunity/apply/3453/?locale=de_DE")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_snb_rejects_duplicate_malformed_and_mismatched_records() -> None:
    def parser_for(payload: dict[str, object]) -> SnbJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, text=search_html(), request=request)
            return httpx.Response(200, json=payload, request=request)

        return SnbJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for(api_payload([api_record(3453), api_record(3453)], total=2)).search(
            LinkedInSearchRequest()
        )
    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        parser_for({"totalJobs": 1}).search(LinkedInSearchRequest())

    url = "https://careers.snb.test/job/Data-Platform-Engineer-3453/3453-de_DE/"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(3453, apply_job_id=9999),
            page_url=url,
            expected_url=url,
            expected_job_id="3453",
            expected_title="Data Platform Engineer 3453",
            expected_cities=["Zürich"],
            expected_employment_type="Festanstellung",
            expected_work_model="hybrid",
        )


def test_snb_rejects_missing_session_contract_and_page_overflow() -> None:
    missing_contract = SnbJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>Jobs</html>", request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="session contract"):
        missing_contract.search(LinkedInSearchRequest())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html(), request=request)
        return httpx.Response(
            200,
            json=api_payload([api_record(3453), api_record(3535)], total=3),
            request=request,
        )

    overflow = SnbJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        max_pages=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        overflow.search(LinkedInSearchRequest())


def test_snb_wraps_listing_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html(), request=request)
        return httpx.Response(503, request=request)

    parser = SnbJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_snb_is_registered_and_jobs_render_as_direct_company_imports() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["snb"]

    assert isinstance(parser, SnbJobsParser)
    assert parser.base_url == settings.snb_jobs_base_url
    assert parser.api_url == settings.snb_jobs_api_url
    assert parser.max_pages == settings.snb_jobs_max_pages
    assert parser.max_catalog_passes == settings.snb_jobs_max_catalog_passes
    assert parser.detail_workers == settings.snb_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SNB", "filters": {}},
            "sources": ["snb", "snb"],
        }
    )
    assert request.sources == ["snb"]

    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": "3453",
                "title": "Data Platform Engineer",
                "location": "Zürich, Schweiz",
                "posted_at": "2026-06-12",
                "employment_type": "Festanstellung",
                "work_model": "hybrid",
                "url": "https://careers.snb.ch/job/Data-Platform-Engineer/3453-de_DE/",
            }
        ),
        job_id="snb-3453",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Swiss National Bank (SNB) import"
    assert stored["company"] == "Schweizerische Nationalbank"
