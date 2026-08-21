from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.datahouse_zurich import DatahouseZurichJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.datahouse.ch/en/career/"
DETAIL_API_URL = "https://api.smart.test/v1/companies/wuestpartner/postings"
JOB_IDS = ("744000141111111", "744000142222222")


def listing_html(
    *,
    zurich_jobs: list[int] | None = None,
    lisbon_jobs: list[int] | None = None,
    site_name: str = "Datahouse",
) -> str:
    zurich_jobs = [0, 1] if zurich_jobs is None else zurich_jobs
    lisbon_jobs = [9] if lisbon_jobs is None else lisbon_jobs

    def card(index: int, city: str) -> str:
        job_id = JOB_IDS[index] if index < len(JOB_IDS) else "744000149999999"
        title = (
            f"System Architect {80 + index * 10}-100% (w/m/d)"
            if city == "Zurich"
            else "Senior Fullstack Software Engineer"
        )
        return f"""
          <div class="wp-block-column">
            <div class="dhsv-teaserbox-block dhsv-teaserbox">
              <a class="link" href="https://jobs.smartrecruiters.com/wuestpartner/{job_id}-role-{index}"></a>
              <div class="image"><img src="role.png" alt="Datahouse"></div>
              <div class="content">
                <h3 class="wp-block-heading">{title}</h3>
                <p>Build reliable cloud-native products for Datahouse clients and teams.</p>
              </div>
            </div>
          </div>
        """

    zurich_cards = "".join(card(index, "Zurich") for index in zurich_jobs)
    lisbon_cards = "".join(card(index, "Lisbon") for index in lisbon_jobs)
    return f"""
      <!doctype html>
      <html lang="en-US">
        <head>
          <title>Career - Datahouse</title>
          <link rel="canonical" href="{BASE_URL}">
          <meta property="og:title" content="Career - Datahouse">
          <meta property="og:site_name" content="{site_name}">
        </head>
        <body>
          <div id="open-positions">
            <div class="wp-block-columns"><p><strong>Open positions</strong></p></div>
            <h3 class="wp-block-heading">Zurich, Switzerland</h3>
            <div class="wp-block-columns">{zurich_cards}</div>
            <h3 class="wp-block-heading">Lisbon, Portugal</h3>
            <div class="wp-block-columns">{lisbon_cards}</div>
          </div>
        </body>
      </html>
    """


def detail_record(index: int, *, active: bool = True) -> dict[str, Any]:
    job_id = JOB_IDS[index]
    title = f"System Architect {80 + index * 10}-100% (w/m/d)"
    return {
        "id": job_id,
        "name": title,
        "refNumber": f"REF{index}",
        "company": {"name": "Wüest Partner", "identifier": "wuestpartner"},
        "location": {
            "city": "Zürich",
            "region": "ZH",
            "country": "ch",
            "remote": False,
            "hybrid": index == 0,
            "fullLocation": "Zürich, ZH, Switzerland",
        },
        "releasedDate": f"2026-08-{10 + index:02d}T09:00:00.000Z",
        "postingUrl": f"https://jobs.smartrecruiters.com/wuestpartner/{job_id}-role-{index}",
        "applyUrl": (
            f"https://jobs.smartrecruiters.com/wuestpartner/{job_id}-role-{index}?oga=true"
        ),
        "active": active,
        "visibility": "PUBLIC",
        "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        "experienceLevel": {"id": "mid_senior_level", "label": "Mid-Senior Level"},
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "title": "Company Description",
                    "text": "<p>Datahouse combines data science and software engineering.</p>",
                },
                "jobDescription": {
                    "title": "Your Mission",
                    "text": "<ul><li>Build cloud-native platforms.</li></ul>",
                },
            }
        },
    }


def parser_for(
    *,
    page: str | None = None,
    details: dict[str, dict[str, Any] | int] | None = None,
    page_status: int = 200,
    **kwargs: Any,
) -> tuple[DatahouseZurichJobsParser, list[str]]:
    requests: list[str] = []
    detail_values = details or {
        job_id: detail_record(index) for index, job_id in enumerate(JOB_IDS)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url == httpx.URL(BASE_URL):
            return httpx.Response(page_status, text=page or listing_html(), request=request)
        job_id = request.url.path.rsplit("/", maxsplit=1)[-1]
        value = detail_values[job_id]
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        return httpx.Response(200, json=value, request=request)

    return (
        DatahouseZurichJobsParser(
            base_url=BASE_URL,
            detail_api_url=DETAIL_API_URL,
            detail_workers=1,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
        requests,
    )


def test_datahouse_collects_only_complete_zurich_catalog_and_enriches_details() -> None:
    parser, requests = parser_for()

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 active Datahouse Zurich vacancies from 2 visible careers-page records"
    )
    assert requests == [
        "/en/career/",
        "/v1/companies/wuestpartner/postings/744000141111111",
        "/v1/companies/wuestpartner/postings/744000142222222",
    ]
    job = result.jobs[0]
    assert job.source == "datahouse_zurich"
    assert job.title == "System Architect 80-100% (w/m/d)"
    assert job.company == "Datahouse AG"
    assert job.location == "Zürich, ZH, Switzerland (Hybrid)"
    assert job.url == ("https://jobs.smartrecruiters.com/wuestpartner/744000141111111-role-0")
    assert job.apply_url == f"{job.url}?oga=true"
    assert job.posted_at == "2026-08-10T09:00:00.000Z"
    assert job.employment_type == "Full-time (80–100%)"
    assert job.seniority == "Mid-Senior Level"
    assert job.description == (
        "Company Description\nDatahouse combines data science and software engineering.\n\n"
        "Your Mission\n- Build cloud-native platforms."
    )
    assert job.raw["catalog_index"] == 0


def test_datahouse_filters_expired_smartrecruiters_records() -> None:
    expired = detail_record(0, active=False)
    expired["postingUrl"] = (
        "https://jobs.smartrecruiters.com/wuestpartner/744000149999999-republished-role"
    )
    expired["applyUrl"] = f"{expired['postingUrl']}?oga=true"
    parser, _ = parser_for(
        details={
            JOB_IDS[0]: expired,
            JOB_IDS[1]: detail_record(1),
        }
    )

    result = parser.search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["System Architect 90-100% (w/m/d)"]
    assert result.message == (
        "Scanned 1 active Datahouse Zurich vacancies from 2 visible careers-page records "
        "(1 expired)"
    )


def test_datahouse_preserves_visible_listing_when_detail_request_fails() -> None:
    parser, _ = parser_for(
        page=listing_html(zurich_jobs=[0], lisbon_jobs=[]),
        details={JOB_IDS[0]: 503},
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "System Architect 80-100% (w/m/d)"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at is None
    assert job.employment_type == "80–100%"
    assert job.description == (
        "Build reliable cloud-native products for Datahouse clients and teams."
    )
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_datahouse_accepts_explicit_empty_zurich_section() -> None:
    parser, requests = parser_for(page=listing_html(zurich_jobs=[], lisbon_jobs=[9]))

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 active Datahouse Zurich vacancies from 0 visible careers-page records"
    )
    assert requests == ["/en/career/"]


def test_datahouse_rejects_identity_catalog_and_detail_inconsistencies() -> None:
    parser, _ = parser_for(page=listing_html(site_name="Another Company"))
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    duplicate_page = listing_html(zurich_jobs=[0, 0], lisbon_jobs=[])
    parser, _ = parser_for(page=duplicate_page)
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        parser.search(LinkedInSearchRequest())

    wrong_detail = detail_record(0)
    wrong_detail["location"] = {"city": "Lisboa", "country": "pt"}
    parser, _ = parser_for(
        page=listing_html(zurich_jobs=[0], lisbon_jobs=[]),
        details={JOB_IDS[0]: wrong_detail},
    )
    fallback = parser.search(LinkedInSearchRequest()).jobs[0]
    assert fallback.location == "Zürich, Switzerland"
    assert "incomplete or inconsistent" in str(fallback.raw["detail_error"])


def test_datahouse_enforces_catalog_limit_and_wraps_page_http_errors() -> None:
    parser, _ = parser_for(max_jobs=1)
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parser.search(LinkedInSearchRequest())

    parser, _ = parser_for(page_status=503)
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_datahouse_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["datahouse_zurich"]
    assert isinstance(parser, DatahouseZurichJobsParser)
    assert parser.base_url == settings.datahouse_zurich_jobs_base_url
    assert parser.detail_api_url == settings.datahouse_zurich_jobs_detail_api_url
    assert parser.max_jobs == settings.datahouse_zurich_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Datahouse Zurich", "filters": {}},
            "sources": ["datahouse_zurich", "datahouse_zurich"],
        }
    )
    assert request.sources == ["datahouse_zurich"]


def test_datahouse_jobs_render_as_direct_company_imports() -> None:
    parser, _ = parser_for(page=listing_html(zurich_jobs=[0], lisbon_jobs=[]))
    job = parser.search(LinkedInSearchRequest()).jobs[0]
    stored = parsed_job_to_stored_job(
        job,
        job_id="datahouse_zurich-744000141111111-role-0",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Datahouse Zurich import"
    assert stored["id"] == "datahouse_zurich-744000141111111-role-0"
