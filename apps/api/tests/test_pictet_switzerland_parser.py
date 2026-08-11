from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.pictet_switzerland import (
    PictetSwitzerlandJobsParser,
    build_search_body,
    parse_catalog_response,
)
from app.services.vacancy_search import create_vacancy_search_runner


def dwr_catalog(rows: list[tuple[str, str, str, str, str]], *, total: int | None = None) -> str:
    total = len(rows) if total is None else total
    declarations: list[str] = []
    assignments: list[str] = []
    posting_refs: list[str] = []
    for index, (job_id, title, date, country, city) in enumerate(rows, start=1):
        job = f"s{index}"
        values = f"s{index + 100}"
        country_var = f"s{index + 200}"
        city_var = f"s{index + 300}"
        declarations.extend(
            [
                f"var {job}={{}};",
                f"var {values}=[];",
                f"var {country_var}={{}};",
                f"var {city_var}={{}};",
            ]
        )
        posting_refs.append(job)
        assignments.append(
            f'{job}.corporatePosting=true;{job}.id={job_id};{job}.jobReqSecKey="key-{job_id}";'
            f'{job}.otherValues={values};{job}.postingDate="{date}";{job}.title="{title}";'
            f"{values}[0]={country_var};{values}[1]={city_var};"
            f'{country_var}.fieldId="filter1";{country_var}.internalVal=null;'
            f'{country_var}.shortVal="{country}";'
            f'{city_var}.fieldId="filter2";{city_var}.internalVal=null;'
            f'{city_var}.shortVal="{city}";'
        )
    return (
        "throw 'allowScriptTagRemoting is false.';\n//#DWR-REPLY\n"
        + "".join(declarations)
        + "var result={};var options={};var pagination={};var postings=[];"
        + f"result.postingCount={total};result.options=options;result.postings=postings;"
        + f"options.pagination=pagination;pagination.pageSize=1000;pagination.totalCount={total};"
        + "".join(f"postings[{index}]={value};" for index, value in enumerate(posting_refs))
        + "".join(assignments)
        + "dwr.engine._remoteHandleCallback('0','0',{results:result});"
    )


def detail_page(
    job_id: str, title: str, *, country: str = "Switzerland", city: str = "Geneva"
) -> str:
    return f"""
    <html><body>
      <h1 id="candidateProfileTitle">Career Opportunities: {title} ({job_id})</h1>
      <div tabindex="0">Requisition ID <b>{job_id}</b> - Posted <b></b> -
        <b>{country}</b> - <b>{city}</b> - <b>Experienced Professionals</b>
      </div>
      <div class="joqReqDescription"><div class="externalPosting">
        <h2>Your role</h2><ul><li>Build secure systems</li></ul>
      </div></div>
      <input id="postedOnFastDate" value="1786091850000" />
    </body></html>
    """


def test_pictet_collects_only_swiss_jobs_and_enriches_details() -> None:
    catalog = dwr_catalog(
        [
            ("124439", "Group Tax Expert", "07\\/08\\/2026", "Switzerland", "Geneva"),
            ("124850", "Transfer Agent", "06\\/08\\/2026", "Luxembourg", "Luxembourg"),
            ("124900", "Senior Engineer", "05\\/08\\/2026", "Switzerland", "Zurich"),
        ]
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and "career_job_req_id" not in request.url.query.decode():
            return httpx.Response(200, text='<script>var ajaxSecKey="token%3d";</script>')
        if request.method == "POST":
            assert parse_qs(request.url.query.decode())["_s.crb"] == ["token="]
            assert request.headers["viewid"].endswith("career.jsp.xhtml")
            assert b"c0-e7=number:1000" in request.content
            return httpx.Response(200, text=catalog)
        job_id = parse_qs(request.url.query.decode())["career_job_req_id"][0]
        title = "Group Tax Expert" if job_id == "124439" else "Senior Engineer"
        city = "Geneva" if job_id == "124439" else "Zurich"
        return httpx.Response(200, text=detail_page(job_id, title, city=city))

    result = PictetSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 Pictet Switzerland vacancies from 3 global postings in 1 catalog pass(es)"
    )
    assert [job.location for job in result.jobs] == ["Geneva, Switzerland", "Zurich, Switzerland"]
    assert result.jobs[0].company == "Pictet"
    assert result.jobs[0].posted_at == "2026-08-07"
    assert result.jobs[0].description == "Your role\n- Build secure systems"
    assert result.jobs[1].seniority == "Senior"
    assert result.jobs[0].apply_url == result.jobs[0].url
    assert len([request for request in requests if request.method == "GET"]) == 3


def test_pictet_preserves_safe_listing_when_detail_fails() -> None:
    catalog = dwr_catalog(
        [("124439", "Group Tax Expert", "07\\/08\\/2026", "Switzerland", "Geneva")]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=catalog)
        if "career_job_req_id" in request.url.query.decode():
            return httpx.Response(503)
        return httpx.Response(200, text='<script>var ajaxSecKey="token%3d";</script>')

    job = (
        PictetSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.location == "Geneva, Switzerland"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_pictet_rejects_incomplete_global_catalog() -> None:
    payload = dwr_catalog(
        [("124439", "Group Tax Expert", "07\\/08\\/2026", "Switzerland", "Geneva")],
        total=2,
    )
    with pytest.raises(DirectCompanyRequestError, match="1 of 2 global postings"):
        parse_catalog_response(
            payload, base_url="https://career012.successfactors.eu/career", max_jobs=100
        )


def test_pictet_rejects_non_swiss_detail_but_keeps_listing() -> None:
    catalog = dwr_catalog(
        [("124439", "Group Tax Expert", "07\\/08\\/2026", "Switzerland", "Geneva")]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, text=catalog)
        if "career_job_req_id" in request.url.query.decode():
            return httpx.Response(
                200, text=detail_page("124439", "Group Tax Expert", country="Luxembourg")
            )
        return httpx.Response(200, text='<script>var ajaxSecKey="token%3d";</script>')

    job = (
        PictetSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.location == "Geneva, Switzerland"
    assert "not a Swiss vacancy" in str(job.raw["detail_error"])


def test_pictet_search_body_requests_complete_first_page() -> None:
    body = build_search_body(
        "https://career012.successfactors.eu/career?company=banquepict",
        page_size=250,
    )
    assert "page=/career?company=banquepict" in body
    assert "c0-methodName=search" in body
    assert "c0-e7=number:250" in body


def test_pictet_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["pictet_switzerland"]
    assert isinstance(parser, PictetSwitzerlandJobsParser)
    assert parser.base_url == settings.pictet_switzerland_jobs_base_url
    assert parser.max_jobs == settings.pictet_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.pictet_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "Pictet", "filters": {}}, "sources": ["pictet_switzerland"]}
    )
    assert request.sources == ["pictet_switzerland"]


def test_pictet_jobs_render_as_direct_company_imports() -> None:
    job = PictetSwitzerlandJobsParser().normalize_job(
        {
            "id": "124439",
            "title": "Group Tax Expert",
            "location": "Geneva, Switzerland",
            "url": (
                "https://career012.successfactors.eu/career?career_ns=job_listing"
                "&company=banquepict&career_job_req_id=124439"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="pictet_switzerland-124439",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Pictet Switzerland import"
