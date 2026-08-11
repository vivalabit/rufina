from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.also import AlsoJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    job_id: int,
    *,
    title: str,
    country: str = "Switzerland",
    department: str = "Finance",
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "country": country,
        "country_lang": country,
        "vk_org": "",
        "url": (
            "https://www.also.test/ec/cms5/en_6000/6000/company/career/"
            f"open-positions/job_details_v2_2_{job_id}.jsp"
        ),
        "img": "https://www.also.test/jobs/image.gif",
        "joblevel": "Experienced",
        "department": department,
    }


def detail_html(
    job_id: int,
    *,
    title: str,
    country: str = "Switzerland",
    locality: str = "Emmen",
) -> str:
    return f"""
    <html><head>
      <meta name="date" content="05.08.2026 13:40:28 CEST">
      <meta name="keywords" content="{title}, {locality}, {country}, jobs">
      <title>{title} - ALSO Holding AG</title>
    </head><body>
      <div class="article job_detail job_detail_v2">
        <h1 class="separat">{title}</h1>
        <h2>{locality}</h2>
        <p>Join our success story.</p>
        <p><b>What you will do:</b></p>
        <ul><li>Prepare reports</li><li>Improve processes</li></ul>
        <p>
          <a href="https://link.ostendis.com/cvdropper/44f4e81edf92404cba52a6018eca879e/DE?src=token"
             class="btn btn-default">Apply</a>
        </p>
      </div>
    </body></html>
    """


def official_catalog() -> list[dict[str, object]]:
    return [
        listing_record(296512, title="Group Reporting Specialist (w/m/d)"),
        listing_record(
            284864,
            title="Sales Consultant Lenovo ISG (w/m/d)",
            department="Sales",
        ),
        listing_record(
            284802,
            title="Marketing Consultant Benelux",
            country="Netherlands",
            department="Marketing",
        ),
    ]


def test_also_collects_complete_catalog_and_enriches_swiss_vacancies() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("jobs_json_4.json"):
            return httpx.Response(200, json={"jobs": official_catalog()})
        job_id = int(request.url.path.removesuffix(".jsp").rsplit("_", maxsplit=1)[-1])
        title = (
            "Group Reporting Specialist (w/m/d)"
            if job_id == 296512
            else "Sales Consultant Lenovo ISG (w/m/d)"
        )
        return httpx.Response(200, text=detail_html(job_id, title=title))

    result = AlsoJobsParser(
        base_url=(
            "https://www.also.test/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp"
        ),
        api_url=(
            "https://www.also.test/ec/cms5/en_6000/6000/company/career/"
            "open-positions/jobs_json_4.json"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 ALSO Switzerland vacancies from 3 official catalog records"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "also"
    assert first.title == "Group Reporting Specialist (w/m/d)"
    assert first.company == "ALSO Holding AG"
    assert first.location == "Emmen, Switzerland"
    assert first.url.endswith("job_details_v2_2_296512.jsp")
    assert first.apply_url == (
        "https://link.ostendis.com/cvdropper/44f4e81edf92404cba52a6018eca879e/DE?src=token"
    )
    assert first.posted_at == "2026-08-05"
    assert first.seniority == "Experienced"
    assert first.description == (
        "Join our success story.\n\n"
        "What you will do:\n\n"
        "- Prepare reports\n"
        "- Improve processes\n\n"
        "Apply"
    )
    assert first.raw["department"] == "Finance"
    assert first.raw["catalog_record"]["id"] == 296512


def test_also_preserves_safe_swiss_listing_when_detail_fails_validation() -> None:
    record = official_catalog()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jobs_json_4.json"):
            return httpx.Response(200, json={"jobs": [record]})
        return httpx.Response(
            200,
            text=detail_html(
                296512,
                title="Group Reporting Specialist (w/m/d)",
                country="Germany",
            ),
        )

    job = (
        AlsoJobsParser(
            base_url="https://www.also.test/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp",
            api_url="https://www.also.test/jobs_json_4.json",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Group Reporting Specialist (w/m/d)"
    assert job.location == "Switzerland"
    assert job.description is None
    assert job.apply_url is None
    assert "non-Swiss vacancy" in str(job.raw["detail_error"])


def test_also_rejects_duplicate_or_unsafe_catalog_records() -> None:
    duplicate = official_catalog()[0]
    duplicate_parser = AlsoJobsParser(
        base_url=(
            "https://www.also.test/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp"
        ),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": [duplicate, duplicate]})
        ),
    )
    unsafe = listing_record(296512, title="Group Reporting Specialist (w/m/d)")
    unsafe["url"] = "https://evil.example/job_details_v2_2_296512.jsp"
    unsafe_parser = AlsoJobsParser(
        base_url=(
            "https://www.also.test/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp"
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"jobs": [unsafe]})),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate_parser.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        unsafe_parser.search(LinkedInSearchRequest())


def test_also_rejects_invalid_catalog_contract() -> None:
    parser = AlsoJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"jobs": {}}))
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_also_wraps_catalog_request_failures() -> None:
    parser = AlsoJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_also_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["also"]
    assert isinstance(parser, AlsoJobsParser)
    assert parser.base_url == settings.also_jobs_base_url
    assert parser.api_url == settings.also_jobs_api_url
    assert parser.detail_workers == settings.also_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ALSO", "filters": {}},
            "sources": ["also", "also"],
        }
    )
    assert request.sources == ["also"]


def test_also_jobs_render_as_direct_company_imports() -> None:
    job = AlsoJobsParser().normalize_job(
        {
            "id": "296512",
            "title": "Group Reporting Specialist (w/m/d)",
            "url": (
                "https://www.also.com/ec/cms5/en_6000/6000/company/career/"
                "open-positions/job_details_v2_2_296512.jsp"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="also-296512",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "ALSO import"
    assert stored["id"] == "also-296512"
