from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.vzug import VzugJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.vzug.com/ch/de/jobs"
CATALOG_URL = "https://jobs.vzug.com/public/v1/careercenter/1002845/?lang=de"
JOB_IDS = (
    "69b70fad-c7ef-4a6a-932f-db7a00ff345d",
    "9b0606a7-88db-48e0-bc2d-d3322282ba92",
)
SLUGS = ("professional-senior-software-engineer", "lead-sap-application-developer")
TITLES = ("Professional/Senior Software Engineer", "Lead SAP Application Developer")


def job_url(index: int) -> str:
    return f"https://jobs.vzug.com/offene-stellen/{SLUGS[index]}/{JOB_IDS[index]}"


def careers_html() -> str:
    return f"""
    <html><head>
      <title>Offene Stellen und Jobs | V-ZUG Schweiz</title>
      <link rel="canonical" href="{BASE_URL}">
    </head><body><c-iframe><iframe src="{CATALOG_URL}"></iframe></c-iframe></body></html>
    """


def listing_html(count: int = 2, declared_count: int | None = None) -> str:
    cards = "".join(
        f"""
        <div class="eight wide column"><div class="job">
          <span>{"Zug" if index == 0 else ""}</span>
          <a href="{job_url(index)}"><h4>{TITLES[index]}</h4></a>
          <p>{"Gestalte die Software unserer Haushaltsgeräte." if index == 0 else "Entwickle unsere SAP-Anwendungen weiter."}</p>
          <a href="{job_url(index)}">Stelleninserat</a>
        </div></div>
        """
        for index in range(count)
    )
    total = count if declared_count is None else declared_count
    return f"""
    <html><head><title>V-Zug Career Center</title></head><body>
      <form id="oh-form">
        <input name="offset" value="0"><input name="limit" value="200">
        <input name="lang" value="de">
      </form>
      <section id="jobResults">
        <div id="jobcount"><strong>{total}</strong> Stellen</div>
        <div class="jobContent countJobRecords">{cards}</div>
      </section>
    </body></html>
    """


def detail_html(index: int) -> str:
    url = job_url(index)
    work_meta = (
        "Du arbeitest 80 - 100% in Zug oder teilweise remote"
        if index == 0
        else "Du arbeitest 100% in der Region Zug"
    )
    return f"""
    <html><head>
      <title>{TITLES[index]} - V-ZUG AG</title>
      <link rel="canonical" href="{url}">
      <meta name="author" content="V-ZUG AG">
    </head><body><main>
      <section id="titleArea"><h1>{TITLES[index]}</h1><span>{work_meta}</span></section>
      <section id="aboutJobRows">
        <div class="aboutRow"><div class="aboutJobTitle"><h3>V-ZUG Software Engineering</h3></div>
          <div class="aboutJobText"><p>Wir entwickeln vernetzte Haushaltsgeräte.</p></div></div>
        <div class="aboutRow"><div class="aboutJobTitle"><h3>Das bietet dir die Stelle</h3></div>
          <div class="aboutJobText"><ul><li>Du gestaltest die Business-Logik.</li></ul></div></div>
      </section>
      <section id="callToActionApply">
        <a href="https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[index]}/ats/">Zur Online-Bewerbung</a>
      </section>
    </main></body></html>
    """


def test_vzug_parses_complete_prospective_catalog_and_details() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if str(request.url) == CATALOG_URL:
            return httpx.Response(200, text=listing_html(), request=request)
        index = JOB_IDS.index(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, text=detail_html(index), request=request)

    result = VzugJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requests == [BASE_URL, CATALOG_URL, job_url(0), job_url(1)]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 V-ZUG vacancies from the complete Prospective catalog")
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "vzug"
    assert job.title == TITLES[0]
    assert job.company == "V-ZUG AG"
    assert job.location == "Zug"
    assert job.url == job_url(0)
    assert job.apply_url == (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[0]}/ats/")
    assert job.employment_type == "80–100%"
    assert job.description == (
        "V-ZUG Software Engineering\n"
        "Wir entwickeln vernetzte Haushaltsgeräte.\n"
        "Das bietet dir die Stelle\n"
        "- Du gestaltest die Business-Logik."
    )
    assert job.raw["id"] == JOB_IDS[0]
    assert job.raw["detail"]["remote"] is True
    assert job.raw["total_available"] == 2

    second = result.jobs[1]
    assert second.location == "Region Zug"
    assert second.employment_type == "100%"


def test_vzug_preserves_listing_record_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if str(request.url) == CATALOG_URL:
            return httpx.Response(200, text=listing_html(count=1), request=request)
        return httpx.Response(503, request=request)

    job = (
        VzugJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == TITLES[0]
    assert job.location == "Zug"
    assert job.apply_url == job_url(0)
    assert job.description == "Gestalte die Software unserer Haushaltsgeräte."
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_vzug_rejects_incomplete_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(
            200,
            text=listing_html(count=1, declared_count=2),
            request=request,
        )

    with pytest.raises(DirectCompanyRequestError, match="declared 2 vacancies but exposed 1"):
        VzugJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_vzug_max_jobs_prevents_silent_catalog_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(200, text=listing_html(), request=request)

    with pytest.raises(DirectCompanyRequestError, match="limit of 1 vacancies"):
        VzugJobsParser(max_jobs=1, transport=httpx.MockTransport(handler)).search(
            LinkedInSearchRequest()
        )


def test_vzug_wraps_request_failures() -> None:
    parser = VzugJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_vzug_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["vzug"]
    assert isinstance(parser, VzugJobsParser)
    assert parser.base_url == settings.vzug_jobs_base_url
    assert parser.catalog_url == settings.vzug_jobs_catalog_url
    assert parser.max_jobs == settings.vzug_jobs_max_jobs
    assert parser.detail_workers == settings.vzug_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "V-ZUG", "filters": {}},
            "sources": ["vzug", "vzug"],
        }
    )
    assert request.sources == ["vzug"]


def test_vzug_jobs_render_as_direct_company_imports() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if str(request.url) == CATALOG_URL:
            return httpx.Response(200, text=listing_html(count=1), request=request)
        return httpx.Response(200, text=detail_html(0), request=request)

    parsed = (
        VzugJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    stored = parsed_job_to_stored_job(
        parsed,
        job_id=f"vzug-{JOB_IDS[0]}",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == f"vzug-{JOB_IDS[0]}"
    assert stored["logo"] == "company"
    assert stored["department"] == "V-ZUG AG import"
    assert stored["company"] == "V-ZUG AG"
