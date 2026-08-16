from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.sonova_switzerland import (
    SonovaSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.sonova.test/careers/?query-1-job-country=switzerland"
API_URL = "https://www.sonova.test/en/jobs_list/active?lang=en"


def listing_record(
    job_id: int,
    *,
    country_id: str = "718",
    country: str = "Switzerland",
    location: str = "Staefa",
    brand: str = "Sonova",
) -> dict[str, object]:
    return {
        "jobReqId": str(job_id),
        "url": (
            "https://career5.successfactors.eu/sfcareer/jobreqcareer?"
            f"company=Sonova&jobId={job_id}&locale=en_US"
        ),
        "title": f"Operator & Specialist {job_id}",
        "contract_type": {
            "id": "219933",
            "label": "Permanent (Full time / Part time)",
        },
        "brand": {"id": "218962", "label": brand},
        "category": {"id": "596", "label": "Engineering"},
        "country": {"id": country_id, "label": country},
        "location": {"id": "1199", "label": location},
    }


def detail_html(job_id: int, *, public_id: int | None = None) -> str:
    public_id = public_id or 1400000000 + job_id
    return f"""
    <html><head>
      <link rel="canonical"
            href="https://jobs.sonova.com/job/Staefa-Operator/{public_id}/">
      <meta property="og:title" content="Operator &amp; Specialist {job_id}">
      <script>window.job = {{"internalId":"{job_id}-en_US"}};</script>
    </head><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="streetAddress" content="Staefa, Switzerland">
        <meta itemprop="datePosted" content="Fri Aug 14 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="Sonova AG">
        <span itemprop="description"><span class="jobdescription">
          <p>Help people enjoy the delight of hearing.</p>
          <ul><li>Build reliable products.</li></ul>
        </span></span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{public_id}/?locale=en_US">Apply</a>
      </div>
    </body></html>
    """


def test_sonova_scans_full_group_snapshot_and_enriches_swiss_records() -> None:
    requests: list[httpx.Request] = []
    catalog = [
        listing_record(99, country_id="701", country="Germany", location="Fellbach"),
        listing_record(101),
        listing_record(102, brand="Advanced Bionics"),
        listing_record(103, location="Murten"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "www.sonova.test":
            assert request.url.params["lang"] == "en"
            return httpx.Response(200, json=catalog, request=request)
        if request.url.host == "career5.successfactors.eu":
            job_id = int(request.url.params["jobId"])
            public_id = 1400000000 + job_id
            return httpx.Response(
                302,
                headers={"Location": f"https://jobs.sonova.com/job/Staefa-Operator/{public_id}/"},
                request=request,
            )
        public_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        job_id = public_id - 1400000000
        page = detail_html(job_id).replace(
            "Staefa, Switzerland",
            "Murten, Switzerland" if job_id == 103 else "Staefa, Switzerland",
        )
        return httpx.Response(200, text=page, request=request)

    result = SonovaSwitzerlandJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 Sonova Switzerland vacancies from 4 "
        "active group catalog records in 1 API request"
    )
    assert len([request for request in requests if request.url.host == "www.sonova.test"]) == 1
    job = result.jobs[0]
    assert job.source == "sonova_switzerland"
    assert job.title == "Operator & Specialist 101"
    assert job.company == "Sonova AG"
    assert job.location == "Staefa, Switzerland"
    assert job.url == "https://jobs.sonova.com/job/Staefa-Operator/1400000101/"
    assert job.apply_url == (
        "https://jobs.sonova.com/talentcommunity/apply/1400000101/?locale=en_US"
    )
    assert job.posted_at == "2026-08-14"
    assert job.employment_type == "Permanent (Full time / Part time)"
    assert job.description == (
        "Help people enjoy the delight of hearing.\n\n- Build reliable products."
    )
    assert job.raw["brand_id"] == "218962"
    assert job.raw["total_available"] == 3
    assert job.raw["group_catalog_total"] == 4
    assert job.raw["detail"]["public_id"] == "1400000101"


def test_sonova_preserves_listing_when_detail_contract_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sonova.test":
            return httpx.Response(200, json=[listing_record(101)], request=request)
        return httpx.Response(200, text="<html>Not a job</html>", request=request)

    job = (
        SonovaSwitzerlandJobsParser(
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.company == "Sonova"
    assert job.location == "Staefa, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at is None
    assert job.description is None
    assert "missing JobPosting" in job.raw["detail_error"]


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ([listing_record(101, country="Germany")], "inconsistent Switzerland facet"),
        ([listing_record(101, location="")], "non-Swiss vacancy"),
        ([listing_record(101), listing_record(101)], "duplicate or malformed"),
        ([{"jobReqId": "101", "country": "Switzerland"}], "country facet"),
    ],
)
def test_sonova_rejects_invalid_catalogs(catalog: list[dict[str, object]], message: str) -> None:
    parser = SonovaSwitzerlandJobsParser(
        api_url=API_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=catalog, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_sonova_enforces_catalog_limit_and_wraps_http_errors() -> None:
    too_large = SonovaSwitzerlandJobsParser(
        api_url=API_URL,
        max_catalog_records=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[listing_record(101), listing_record(102)],
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = SonovaSwitzerlandJobsParser(
        api_url=API_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_sonova_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["sonova_switzerland"]
    assert isinstance(parser, SonovaSwitzerlandJobsParser)
    assert parser.api_url == settings.sonova_switzerland_jobs_api_url
    assert parser.max_catalog_records == settings.sonova_switzerland_jobs_max_catalog_records
    assert parser.detail_workers == settings.sonova_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Sonova", "filters": {}},
            "sources": ["sonova_switzerland", "sonova_switzerland"],
        }
    )
    assert request.sources == ["sonova_switzerland"]


def test_sonova_jobs_render_as_direct_company_imports() -> None:
    job = SonovaSwitzerlandJobsParser().normalize_job(
        {
            "id": "164409",
            "title": "Operator (m/f/d)",
            "brand": "Sonova",
            "location": "Staefa, Switzerland",
            "url": (
                "https://career5.successfactors.eu/sfcareer/jobreqcareer?"
                "company=Sonova&jobId=164409&locale=en_US"
            ),
            "posted_at": None,
            "contract_type": "Permanent (Full time / Part time)",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="sonova_switzerland-164409",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Sonova Group import"
    assert stored["company"] == "Sonova"
    assert stored["id"] == "sonova_switzerland-164409"
