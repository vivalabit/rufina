from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.axa_schweiz import AxaSchweizJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    job_id = str(23_000 + index)
    return {
        "slug": job_id,
        "language": "de-de",
        "languages": ["de-de"],
        "req_id": job_id,
        "title": f"Platform Engineer {index}",
        "description": "Build reliable insurance platforms. Work with the team.",
        "location_name": "Winterthur - General-Guisan-Strasse",
        "street_address": "General-Guisan-Strasse 40",
        "city": "WINTERTHUR",
        "country": "Switzerland",
        "country_code": "CH",
        "postal_code": "8400",
        "tags1": ["Full-time"],
        "tags2": ["Permanent contract"],
        "tags3": ["AXA Switzerland"],
        "tags5": ["Experienced"],
        "employment_type": "FULL_TIME",
        "hiring_organization": "AXA",
        "posted_date": "2026-08-06T05:34:00+0000",
        "apply_url": f"https://careers-de-axa.icims.com/jobs/{job_id}/login",
        "meta_data": {
            "canonical_url": f"https://careers.axa.com/jobs/{job_id}?lang=de-de",
        },
        "full_location": "WINTERTHUR, Switzerland",
    }


def wrapped(record: dict[str, object]) -> dict[str, object]:
    return {"data": record}


def test_axa_schweiz_fetches_every_page_and_normalizes_records() -> None:
    records = [listing_record(index) for index in range(102)]
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/jobs"
        assert request.url.params["country"] == "Switzerland"
        assert request.url.params["limit"] == "100"
        page = int(request.url.params["page"])
        requested_pages.append(page)
        offset = (page - 1) * 100
        return httpx.Response(
            200,
            json={
                "totalCount": len(records),
                "jobs": [wrapped(record) for record in records[offset : offset + 100]],
                "count": 5,
            },
        )

    parser = AxaSchweizJobsParser(
        base_url="https://careers.axa.example.test/jobs?country=Switzerland&page=1",
        api_url="https://careers.axa.example.test/api/jobs",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_pages == [1, 2]
    assert result.status == "completed"
    assert result.message == "Scanned 102 AXA Schweiz vacancies across 2 API pages"
    assert len(result.jobs) == 102
    first = result.jobs[0]
    assert first.source == "axa_schweiz"
    assert first.title == "Platform Engineer 0"
    assert first.company == "AXA Switzerland"
    assert first.location == "WINTERTHUR, Switzerland"
    assert first.url == "https://careers.axa.com/jobs/23000?lang=de-de"
    assert first.apply_url == "https://careers-de-axa.icims.com/jobs/23000/login"
    assert first.posted_at == "2026-08-06T05:34:00+0000"
    assert first.employment_type == "Full-time, Permanent contract"
    assert first.seniority == "Experienced"
    assert first.description == (
        "Build reliable insurance platforms. Work with the team."
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 102


def test_axa_schweiz_repeats_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(102)]
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested_pages.append(page)
        if page == 1:
            page_records = records[:100]
        elif requested_pages.count(2) == 1:
            page_records = [records[99], records[100]]
        else:
            page_records = records[100:]
        return httpx.Response(
            200,
            json={
                "totalCount": len(records),
                "jobs": [wrapped(record) for record in page_records],
            },
        )

    parser = AxaSchweizJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_pages == [1, 2, 1, 2]
    assert len(result.jobs) == 102


def test_axa_schweiz_rejects_invalid_jobs_payload() -> None:
    parser = AxaSchweizJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"totalCount": 4, "jobs": {}},
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_axa_schweiz_does_not_silently_truncate_above_page_limit() -> None:
    parser = AxaSchweizJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "totalCount": 201,
                    "jobs": [wrapped(listing_record(index)) for index in range(100)],
                },
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_axa_schweiz_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["axa_schweiz"]
    assert isinstance(parser, AxaSchweizJobsParser)
    assert parser.api_url == settings.axa_schweiz_jobs_api_url
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AXA Schweiz", "filters": {}},
            "sources": ["axa_schweiz", "axa_schweiz"],
        }
    )
    assert request.sources == ["axa_schweiz"]


def test_axa_schweiz_jobs_render_as_direct_company_imports() -> None:
    parser = AxaSchweizJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="axa_schweiz-23001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "AXA Schweiz import"
    assert stored["id"] == "axa_schweiz-23001"
