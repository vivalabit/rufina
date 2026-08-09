from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.swissgrid import SwissgridJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(job_id: int) -> dict[str, str]:
    return {
        "id": str(job_id),
        "title": f"Cloud Engineer ({80 + job_id % 10}-100%)",
        "descriptionUrl": (
            "https://career2.successfactors.test/sfcareer/jobreqcareer"
            f"?jobId={job_id}&locale=de_DE&company=Swissgrid"
        ),
        "applicationUrl": "",
        "placeOfWork": "Aarau",
        "department": "IT & Telecommunications",
        "onlineSince": "06.08.2026",
        "typeOfEmployment": "Full time",
        "limitation": "Unlimited",
        "entryLevel": "Employee",
    }


def listing_payload(ids: list[int]) -> dict[str, object]:
    return {
        "config": {"cacheDurationInSeconds": 10},
        "jobs": [listing_record(job_id) for job_id in ids],
        "filters": [],
    }


def detail_html(job_id: int) -> str:
    internal_id = 1_360_000_000 + job_id
    second_location = (
        '<meta itemprop="addressLocality" content="Landquart">'
        if job_id == 1610
        else ""
    )
    return f"""
    <html><head>
      <meta property="og:title" content="Cloud Engineer ({80 + job_id % 10}-100%)">
    </head><body>
      <div class="jobDisplayShell" itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Thu Aug 06 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="Swissgrid">
        <span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
          <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
            <meta itemprop="addressLocality" content="Aarau">
            {second_location}
            <meta itemprop="addressRegion" content="AG">
            <meta itemprop="postalCode" content="5001">
          </span>
        </span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p>Help keep the Swiss transmission grid secure.</p>
            <h4>Your responsibilities</h4>
            <ul><li>Build cloud platforms.</li><li>Operate reliable services.</li></ul>
          </span>
        </span>
        <a class="btn apply dialogApplyBtn"
           href="/talentcommunity/apply/{internal_id}/?locale=de_DE">
          Apply now
        </a>
      </div>
      <script>window.config = {{"internalId":"{job_id}-de_DE"}};</script>
    </body></html>
    """


def test_swissgrid_scans_and_enriches_complete_catalog() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/.rest/cloud/component-data"):
            assert "joblist_transferred_11" in request.url.params["path"]
            return httpx.Response(200, json=listing_payload([1609, 1610]))
        job_id = int(request.url.params["jobId"])
        return httpx.Response(200, text=detail_html(job_id))

    parser = SwissgridJobsParser(
        base_url="https://www.swissgrid.test/en/home/career/jobs.html",
        api_url=(
            "https://www.swissgrid.test/.rest/cloud/component-data"
            "?path=/swissgrid/en/home/career/jobs/main/joblist_transferred_11"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Swissgrid vacancies from the full catalog endpoint"
    )
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "swissgrid"
    assert first.title == "Cloud Engineer (89-100%)"
    assert first.company == "Swissgrid"
    assert first.location == "Aarau"
    assert first.url == (
        "https://career2.successfactors.test/sfcareer/jobreqcareer"
        "?jobId=1609&locale=de_DE&company=Swissgrid"
    )
    assert first.apply_url == (
        "https://career2.successfactors.test/talentcommunity/"
        "apply/1360001609/?locale=de_DE"
    )
    assert first.posted_at == "2026-08-06"
    assert first.employment_type == "Full time, 89-100%"
    assert first.seniority == "Employee"
    assert first.description == (
        "Help keep the Swiss transmission grid secure.\n\n"
        "Your responsibilities\n\n"
        "- Build cloud platforms.\n"
        "- Operate reliable services."
    )
    assert first.raw["department"] == "IT & Telecommunications"
    assert first.raw["detail"]["id"] == "1609"
    assert result.jobs[1].location == "Aarau, Landquart"


def test_swissgrid_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.rest/cloud/component-data"):
            return httpx.Response(200, json=listing_payload([1609]))
        return httpx.Response(503, text="temporarily unavailable")

    parser = SwissgridJobsParser(
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Cloud Engineer (89-100%)"
    assert job.location == "Aarau"
    assert job.url and "jobId=1609" in job.url
    assert job.apply_url is None
    assert job.posted_at == "2026-08-06"
    assert job.employment_type == "Full time, 89-100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_swissgrid_rejects_invalid_jobs_payload() -> None:
    parser = SwissgridJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": {}})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_swissgrid_rejects_duplicate_ids() -> None:
    record = listing_record(1609)
    parser = SwissgridJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": [record, record]})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_swissgrid_rejects_mismatched_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.rest/cloud/component-data"):
            return httpx.Response(200, json=listing_payload([1609]))
        return httpx.Response(200, text=detail_html(1610))

    parser = SwissgridJobsParser(transport=httpx.MockTransport(handler))

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Cloud Engineer (89-100%)"
    assert job.description is None
    assert "different vacancy" in str(job.raw["detail_error"])


def test_swissgrid_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["swissgrid"]
    assert isinstance(parser, SwissgridJobsParser)
    assert parser.base_url == settings.swissgrid_jobs_base_url
    assert parser.api_url == settings.swissgrid_jobs_api_url
    assert parser.detail_workers == settings.swissgrid_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Swissgrid", "filters": {}},
            "sources": ["swissgrid", "swissgrid"],
        }
    )
    assert request.sources == ["swissgrid"]


def test_swissgrid_jobs_render_as_direct_company_imports() -> None:
    parser = SwissgridJobsParser()
    job = parser.normalize_job(listing_record(1609))
    stored = parsed_job_to_stored_job(
        job,
        job_id="swissgrid-1609",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Swissgrid import"
    assert stored["id"] == "swissgrid-1609"
