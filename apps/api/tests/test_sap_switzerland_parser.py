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
from app.services.parsers.companies.sap_switzerland import (
    SapSwitzerlandJobsParser,
    parse_new_detail_html,
    parse_new_listing_html,
)
from app.services.vacancy_search import create_vacancy_search_runner


def new_record(job_id: str) -> dict[str, str]:
    return {
        "id": job_id,
        "title": f"SAP Cloud Engineer {job_id}",
        "url": f"/en/jobs/{job_id}/cloud-engineer/",
        "locations": "Zurich, Switzerland",
    }


def flight_script(payload: object) -> str:
    stream = "2e:" + json.dumps(payload)
    # Real Flight payloads can split JSON across script tags.
    return "".join(
        f"<script>self.__next_f.push({json.dumps([1, chunk])})</script>"
        for chunk in (stream[:31], stream[31:])
    )


def new_listing_html(records: list[dict[str, str]], *, total: int, page: int = 1) -> str:
    metadata = {
        "jobs": records,
        "totalJobs": total,
        "totalPages": max(1, total),
        "currentPage": page,
        "pageSize": 1,
    }
    links = "".join(f'<a href="{record["url"]}">{record["title"]}</a>' for record in records)
    # Repeated hydration copies use different component references, but same jobs.
    payload = [metadata, {**metadata, "displayMetadata": "$33:props:display"}]
    return f"<title>Jobs | SAP Careers</title>{links}{flight_script(payload)}"


def new_detail_html(record: dict[str, str], *, country: str = "CH") -> str:
    url = "https://jobs.sap.com" + record["url"]
    posting = {
        "@type": "JobPosting",
        "url": url,
        "title": record["title"],
        "hiringOrganization": {"name": "SAP Careers", "url": "https://jobs.sap.com"},
        "jobLocation": {"address": {"addressCountry": country, "addressLocality": "Zurich"}},
        "description": r"\u003cp>Build cloud applications and support enterprise customers. "
        r"Collaborate with the Swiss team to deliver reliable software platforms.\u003c/p>",
        "datePosted": "2026-10-27",
        "employmentType": "FULL_TIME",
        "identifier": {"value": "REF3170F"},
    }
    data = {
        **record,
        "applicationUrl": (
            f"https://jobs.smartrecruiters.com/SAPITBusinessSysteme/{record['id']}-cloud-engineer?oga=true"
        ),
    }
    return (
        f'<link rel="canonical" href="{url}">'
        f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        + flight_script({"jobData": data})
    )


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


@pytest.mark.parametrize("duplicate_page", [False, True])
def test_sap_migration_collects_both_complete_swiss_catalogs(duplicate_page: bool) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "careers.sap.com":
            if request.url.path.startswith("/go/"):
                return httpx.Response(200, text=listing_html([101], start=1, end=1, total=1))
            return httpx.Response(200, text=detail_html(101))
        if request.url.path == "/en/jobs/":
            assert request.url.params["country"] == "Switzerland"
            page = int(request.url.params["page"])
            index = 1 if duplicate_page else page
            return httpx.Response(
                200, text=new_listing_html([new_record(f"744000{index}")], total=2, page=page)
            )
        return httpx.Response(200, text=new_detail_html(new_record(request.url.path.split("/")[3])))

    parser = SapSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
    if duplicate_page:
        with pytest.raises(DirectCompanyRequestError, match="duplicate or missing"):
            parser.search(LinkedInSearchRequest(results_limit=1))
        return
    result = parser.search(LinkedInSearchRequest(results_limit=1))
    assert [job.raw["id"] for job in result.jobs] == ["101", "7440001", "7440002"]
    assert all(job.description and "detail_error" not in job.raw for job in result.jobs)
    assert result.jobs[0].url.startswith("https://careers.sap.com/job/")
    assert result.jobs[1].apply_url.startswith("https://jobs.smartrecruiters.com/SAP")
    assert "\\u003c" not in result.jobs[1].description
    assert result.message.endswith("across 3 page requests")


@pytest.mark.parametrize("corruption", ["country", "range", "hidden", "foreign_url"])
def test_sap_new_catalog_rejects_unverified_records(corruption: str) -> None:
    record = new_record("7440001")
    if corruption == "country":
        record["locations"] = "Walldorf, Germany"
    if corruption == "foreign_url":
        record["url"] = "https://attacker.example/en/jobs/7440001/cloud-engineer/"
    page = new_listing_html([record], total=1)
    if corruption == "range":
        page = page.replace('\\"pageSize\\": 1', '\\"pageSize\\": 0')
    if corruption == "hidden":
        page = page.replace(f'<a href="{record["url"]}">', "<a>")
    with pytest.raises(DirectCompanyRequestError):
        parse_new_listing_html(
            page, page_url="https://jobs.sap.com/en/jobs/?country=Switzerland", expected_page=1
        )


@pytest.mark.parametrize("country", ["CH", "DE"])
def test_sap_new_detail_validates_country_and_application_identity(country: str) -> None:
    record = new_record("7440001")
    expected = {
        **record,
        "url": "https://jobs.sap.com" + record["url"],
        "location": record["locations"],
    }
    page = new_detail_html(record, country=country)
    if country == "DE":
        with pytest.raises(DirectCompanyRequestError, match="Swiss JobPosting"):
            parse_new_detail_html(page, page_url=expected["url"], expected_record=expected)
    else:
        assert parse_new_detail_html(page, page_url=expected["url"], expected_record=expected)[
            "description"
        ].startswith("Build cloud")
        with pytest.raises(DirectCompanyRequestError, match="application URL"):
            parse_new_detail_html(
                page.replace("SAPITBusinessSysteme/7440001-", "SAPITBusinessSysteme/7440002-"),
                page_url=expected["url"],
                expected_record=expected,
            )


@pytest.mark.parametrize("pages", [0, 1])
def test_sap_new_catalog_accepts_explicit_empty_results(pages: int) -> None:
    page = new_listing_html([], total=0).replace(
        '\\"totalPages\\": 1', f'\\"totalPages\\": {pages}'
    )
    records, metadata = parse_new_listing_html(
        page,
        page_url="https://jobs.sap.com/en/jobs/?country=Switzerland",
        expected_page=1,
    )
    assert records == [] and metadata == {"total": 0, "pages": 1}


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
