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
from app.services.parsers.companies.suva import SuvaJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def search_html(*, csrf_token: str = "csrf-token") -> str:
    return f'<html><script>var CSRFToken = "{csrf_token}";</script></html>'


def listing_payload(ids: list[int], *, total: int) -> dict[str, object]:
    return {
        "jobSearchResult": [
            {
                "response": {
                    "id": str(job_id),
                    "unifiedStandardTitle": f"Cloud Engineer {job_id} 80 - 100 %",
                    "unifiedUrlTitle": f"Cloud-Engineer-{job_id}-80-100",
                    "unifiedStandardStart": "07.08.26",
                    "jobLocationShort": ["Luzern ", " Zürich "],
                    "supportedLocales": ["de_DE"],
                }
            }
            for job_id in ids
        ],
        "totalJobs": total,
    }


def detail_html(job_id: int, *, title: str | None = None) -> str:
    job_title = title or f"Cloud Engineer {job_id} 80 - 100 %"
    return f"""
    <html><head><meta name="keywords" content="{job_title}"></head><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <span itemprop="description">
          <p><strong>Was du bewirkst</strong></p>
          <ul><li>Du entwickelst sichere Plattformen.</li></ul>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=de_DE">Jetzt bewerben</a>
      </div>
      <div id="unifyJobFooter">
        <div class="joblayouttoken">
          <span class="rtltextaligneligible">
            <p><strong>Wie du bei uns wächst</strong></p>
            <ul><li>Du entwickelst dich fachlich weiter.</li></ul>
          </span>
        </div>
      </div>
    </body></html>
    """


def test_suva_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html())
        if request.method == "POST":
            page_number = json.loads(request.content)["pageNumber"]
            payload = (
                listing_payload([101, 102], total=3)
                if page_number == 0
                else listing_payload([103], total=3)
            )
            return httpx.Response(200, json=payload)
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
        return httpx.Response(200, text=detail_html(job_id))

    parser = SuvaJobsParser(
        base_url="https://jobs.suva.test/search/",
        api_url="https://jobs.suva.test/services/recruiting/v1/jobs",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Suva vacancies from 3 catalog records across 2 page requests"
    )
    api_requests = [request for request in requests if request.method == "POST"]
    assert len(api_requests) == 2
    assert api_requests[0].headers["x-csrf-token"] == "csrf-token"
    assert json.loads(api_requests[0].content) == {
        "locale": "de_DE",
        "pageNumber": 0,
        "sortBy": "",
        "keywords": "",
        "location": "",
        "facetFilters": {},
        "brand": "",
        "skills": [],
        "categoryId": 0,
        "alertId": "",
        "rcmCandidateId": "",
    }
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "suva"
    assert first.title == "Cloud Engineer 101 80 - 100 %"
    assert first.company == "Suva"
    assert first.location == "Luzern, Zürich"
    assert first.url == "https://jobs.suva.test/job/Cloud-Engineer-101-80-100/101-de_DE/"
    assert first.apply_url == ("https://jobs.suva.test/talentcommunity/apply/101/?locale=de_DE")
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "80 - 100 %"
    assert first.description == (
        "Was du bewirkst\n\n"
        "- Du entwickelst sichere Plattformen.\n\n"
        "Wie du bei uns wächst\n\n"
        "- Du entwickelst dich fachlich weiter."
    )
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["id"] == "101"


def test_suva_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html())
        if request.method == "GET":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
            return httpx.Response(200, text=detail_html(job_id))
        page_number = json.loads(request.content)["pageNumber"]
        if page_number == 0:
            first_page_calls += 1
            return httpx.Response(200, json=listing_payload([101, 102], total=3))
        ids = [102] if first_page_calls == 1 else [103]
        return httpx.Response(200, json=listing_payload(ids, total=3))

    parser = SuvaJobsParser(
        base_url="https://jobs.suva.test/search/",
        api_url="https://jobs.suva.test/services/recruiting/v1/jobs",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_suva_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/search/":
            return httpx.Response(200, text=search_html())
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload([101], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = SuvaJobsParser(
        base_url="https://jobs.suva.test/search/",
        api_url="https://jobs.suva.test/services/recruiting/v1/jobs",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Cloud Engineer 101 80 - 100 %"
    assert job.location == "Luzern, Zürich"
    assert job.description is None
    assert job.apply_url == ("https://jobs.suva.test/talentcommunity/apply/101/?locale=de_DE")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_suva_rejects_search_page_without_csrf_token() -> None:
    parser = SuvaJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="CSRF token"):
        parser.search(LinkedInSearchRequest())


def test_suva_rejects_listing_without_catalog_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html())
        return httpx.Response(200, json={"jobs": []})

    parser = SuvaJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="catalog contract"):
        parser.search(LinkedInSearchRequest())


def test_suva_enforces_catalog_page_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html())
        return httpx.Response(200, json=listing_payload([101, 102], total=3))

    parser = SuvaJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_suva_wraps_listing_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=search_html())
        return httpx.Response(503)

    parser = SuvaJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_suva_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["suva"]
    assert isinstance(parser, SuvaJobsParser)
    assert parser.base_url == settings.suva_jobs_base_url
    assert parser.api_url == settings.suva_jobs_api_url
    assert parser.max_pages == settings.suva_jobs_max_pages
    assert parser.max_catalog_passes == settings.suva_jobs_max_catalog_passes
    assert parser.detail_workers == settings.suva_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Suva", "filters": {}},
            "sources": ["suva", "suva"],
        }
    )
    assert request.sources == ["suva"]


def test_suva_jobs_render_as_direct_company_imports() -> None:
    job = SuvaJobsParser().normalize_job(
        {
            "id": "101",
            "title": "Cloud Engineer 80 - 100 %",
            "location": "Luzern",
            "url": "https://jobs.suva.ch/job/Cloud-Engineer/101-de_DE/",
            "posted_at": "07.08.26",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="suva-101",
        added_at=datetime.now(UTC),
    )

    assert stored["id"] == "suva-101"
    assert stored["logo"] == "company"
    assert stored["department"] == "Suva import"
    assert stored["company"] == "Suva"
