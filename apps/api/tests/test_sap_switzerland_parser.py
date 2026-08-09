from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.sap_switzerland import (
    SapSwitzerlandJobsParser,
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
               href="/job/Zurich-SAP-Cloud-Engineer-8058/{job_id}/">
              SAP Cloud Engineer {job_id}
            </a>
          </td>
          <td class="colLocation">
            <span class="jobLocation">Zürich-Flughafen, Zurich, CH, 8058</span>
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
    job_title = title or f"SAP Cloud Engineer {job_id}"
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Fri Aug 07 02:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="SAP">
        <span data-careersite-propertyid="department">Software-Design and Development</span>
        <span itemprop="title" data-careersite-propertyid="title">{job_title}</span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <p><strong>We help the world run better</strong></p>
            <h3>What you'll do</h3>
            <ul><li>Build cloud services.</li><li>Collaborate with the team.</li></ul>
          </span>
        </span>
        <span data-careersite-propertyid="facility">REQ-{job_id}</span>
        <span data-careersite-propertyid="date">Aug 7, 2026</span>
        <span data-careersite-propertyid="department">Software-Design and Development</span>
        <span data-careersite-propertyid="customfield3">Professional</span>
        <span data-careersite-propertyid="shifttype">Regular Full Time</span>
        <span data-careersite-propertyid="travel">0 - 10%</span>
        <span data-careersite-propertyid="location">
          <span class="jobGeoLocation">Zürich-Flughafen, Zurich, CH, 8058</span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_sap_switzerland_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/go/SAP-Jobs-in-Switzerland/915101/":
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

    parser = SapSwitzerlandJobsParser(
        base_url="https://jobs.sap.test/go/SAP-Jobs-in-Switzerland/915101/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 SAP Switzerland vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [
        request for request in requests if request.url.path == "/go/SAP-Jobs-in-Switzerland/915101/"
    ]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["locale"] == "en_US"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[0].url.params["sortDirection"] == "desc"
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "sap_switzerland"
    assert first.title == "SAP Cloud Engineer 101"
    assert first.company == "SAP"
    assert first.location == "Zürich-Flughafen, Zurich, CH, 8058"
    assert first.url == "https://jobs.sap.test/job/Zurich-SAP-Cloud-Engineer-8058/101/"
    assert first.apply_url == ("https://jobs.sap.test/talentcommunity/apply/101/?locale=en_US")
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Regular Full Time"
    assert first.seniority == "Professional"
    assert first.description == (
        "We help the world run better\n\n"
        "What you'll do\n\n"
        "- Build cloud services.\n"
        "- Collaborate with the team."
    )
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["requisition_id"] == "REQ-101"
    assert first.raw["detail"]["work_area"] == "Software-Design and Development"
    assert first.raw["detail"]["expected_travel"] == "0 - 10%"


def test_sap_switzerland_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/go/SAP-Jobs-in-Switzerland/915101/":
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

    parser = SapSwitzerlandJobsParser(
        base_url="https://jobs.sap.test/go/SAP-Jobs-in-Switzerland/915101/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_sap_switzerland_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go/SAP-Jobs-in-Switzerland/915101/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SapSwitzerlandJobsParser(
        base_url="https://jobs.sap.test/go/SAP-Jobs-in-Switzerland/915101/",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "SAP Cloud Engineer 101"
    assert job.location == "Zürich-Flughafen, Zurich, CH, 8058"
    assert job.description is None
    assert job.apply_url == ("https://jobs.sap.test/talentcommunity/apply/101/?locale=en_US")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_sap_switzerland_rejects_duplicate_listing_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go/SAP-Jobs-in-Switzerland/915101/":
            return httpx.Response(
                200,
                text=listing_html([101, 101], start=1, end=2, total=2),
            )
        return httpx.Response(200, text=detail_html(101))

    parser = SapSwitzerlandJobsParser(
        base_url="https://jobs.sap.test/go/SAP-Jobs-in-Switzerland/915101/",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest(deduplicate=True))


def test_sap_switzerland_rejects_listing_without_catalog_contract() -> None:
    parser = SapSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_sap_switzerland_enforces_catalog_page_limit() -> None:
    parser = SapSwitzerlandJobsParser(
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


def test_sap_switzerland_wraps_listing_request_failures() -> None:
    parser = SapSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_sap_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["sap_switzerland"]
    assert isinstance(parser, SapSwitzerlandJobsParser)
    assert parser.base_url == settings.sap_switzerland_jobs_base_url
    assert parser.max_pages == settings.sap_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.sap_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.sap_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SAP Switzerland", "filters": {}},
            "sources": ["sap_switzerland", "sap_switzerland"],
        }
    )
    assert request.sources == ["sap_switzerland"]


def test_sap_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = SapSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "101",
            "title": "SAP Cloud Engineer",
            "location": "Zürich-Flughafen, Zurich, CH, 8058",
            "url": "https://jobs.sap.com/job/Zurich-SAP-Cloud-Engineer/101/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="sap_switzerland-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "SAP Switzerland import"
    assert stored["id"] == "sap_switzerland-101"
