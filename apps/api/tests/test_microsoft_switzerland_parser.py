from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.microsoft_switzerland import (
    MICROSOFT_SWITZERLAND_LOCATION,
    MicrosoftSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(job_id: int, title: str) -> dict[str, object]:
    return {
        "id": job_id,
        "displayJobId": str(job_id),
        "name": title,
        "locations": ["Switzerland, Zürich, Zürich"],
        "standardizedLocations": ["Zürich, ZH, CH"],
        "postedTs": 1785768190,
        "department": "Software Engineering",
        "workLocationOption": "onsite",
        "atsJobId": str(job_id),
        "positionUrl": f"/careers/job/{job_id}",
    }


def listing_response(records: list[dict[str, object]], total: int) -> dict[str, object]:
    return {
        "status": 200,
        "error": {"message": "", "body": ""},
        "data": {"positions": records, "count": total},
        "metadata": None,
    }


def detail_response(record: dict[str, object]) -> dict[str, object]:
    detail = {
        **record,
        "location": "Switzerland, Zürich, Zürich",
        "publicUrl": f"https://apply.careers.microsoft.test/careers/job/{record['id']}",
        "efcustomTextEmploymentType": ["Full-Time"],
        "efcustomTextRoletype": ["Individual Contributor"],
        "efcustomTextWorkSite": ["3 days / week in-office"],
        "jobDescription": (
            "<b>Overview</b><br><div><p>Build reliable cloud systems.</p></div>"
            "<b>Responsibilities</b><br><ul><li>Collaborate with the team.</li></ul>"
        ),
        "positionExtraDetails": {"blogs": [{"title": "Repeated marketing content"}]},
    }
    return {
        "status": 200,
        "error": {"message": "", "body": ""},
        "data": detail,
        "metadata": None,
    }


def test_microsoft_switzerland_scans_every_page_and_enriches_jobs() -> None:
    records = [vacancy(1000 + index, f"Microsoft role {index}") for index in range(11)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/search"):
            offset = int(request.url.params["start"])
            return httpx.Response(
                200,
                json=listing_response(records[offset : offset + 10], len(records)),
            )
        job_id = int(request.url.params["position_id"])
        record = next(item for item in records if item["id"] == job_id)
        return httpx.Response(200, json=detail_response(record))

    parser = MicrosoftSwitzerlandJobsParser(
        base_url="https://apply.careers.microsoft.test/careers",
        api_url="https://apply.careers.microsoft.test/api/pcsx/search",
        detail_api_url="https://apply.careers.microsoft.test/api/pcsx/position_details",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 11 Microsoft Switzerland vacancies across 2 API pages (11 listed)"
    )
    assert len(result.jobs) == 11
    listing_requests = [request for request in requests if request.url.path.endswith("/search")]
    detail_requests = [
        request for request in requests if request.url.path.endswith("/position_details")
    ]
    assert [request.url.params["start"] for request in listing_requests] == ["0", "10"]
    assert len(detail_requests) == 11
    assert listing_requests[0].url.params["domain"] == "microsoft.com"
    assert listing_requests[0].url.params["location"] == MICROSOFT_SWITZERLAND_LOCATION
    assert listing_requests[0].url.params["sort_by"] == "distance"
    assert listing_requests[0].url.params["filter_distance"] == "160"
    assert listing_requests[0].url.params["filter_include_remote"] == "1"
    assert listing_requests[0].url.params["filter_include_relocation"] == "0"
    assert detail_requests[0].url.params["hl"] == "en"

    first = result.jobs[0]
    assert first.source == "microsoft_switzerland"
    assert first.title == "Microsoft role 0"
    assert first.company == "Microsoft"
    assert first.location == "Switzerland, Zürich, Zürich"
    assert first.url == "https://apply.careers.microsoft.test/careers/job/1000"
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-03T14:43:10Z"
    assert first.employment_type == "Full-Time"
    assert first.seniority == "Individual Contributor"
    assert first.description == (
        "Overview\nBuild reliable cloud systems.\n\nResponsibilities\n• Collaborate with the team."
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["total_available"] == 11
    assert first.raw["detail"]["efcustomTextWorkSite"] == ["3 days / week in-office"]
    assert first.raw["detail"]["raw_fields_removed"] == ["positionExtraDetails"]
    assert "positionExtraDetails" not in first.raw["detail"]
    assert result.jobs[-1].raw["listing_page"] == 2


def test_microsoft_switzerland_keeps_listing_when_detail_fails() -> None:
    record = vacancy(1000, "Software Engineer")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = MicrosoftSwitzerlandJobsParser(transport=httpx.MockTransport(handler))

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Software Engineer"
    assert result.jobs[0].url.endswith("/careers/job/1000")
    assert result.jobs[0].description is None
    assert "503 Service Unavailable" in result.jobs[0].raw["detail_error"]


def test_microsoft_switzerland_deduplicates_when_requested() -> None:
    record = vacancy(1000, "Software Engineer")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=listing_response([record, record], 2))
        return httpx.Response(200, json=detail_response(record))

    parser = MicrosoftSwitzerlandJobsParser(transport=httpx.MockTransport(handler))

    assert len(parser.search(LinkedInSearchRequest(deduplicate=True)).jobs) == 1
    assert len(parser.search(LinkedInSearchRequest(deduplicate=False)).jobs) == 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": 500, "data": {}},
        {"status": 200, "data": {"count": "1", "positions": []}},
        {"status": 200, "data": {"count": 1, "jobs": []}},
        {"status": 200, "data": {"count": 1, "positions": [{}]}},
    ],
)
def test_microsoft_switzerland_rejects_invalid_payload(payload: object) -> None:
    parser = MicrosoftSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="jobs response"):
        parser.search(LinkedInSearchRequest())


def test_microsoft_switzerland_rejects_incomplete_page() -> None:
    parser = MicrosoftSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response([vacancy(1000, "Role")], 2))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="returned 1 vacancies"):
        parser.search(LinkedInSearchRequest())


def test_microsoft_switzerland_enforces_page_limit() -> None:
    records = [vacancy(1000 + index, f"Role {index}") for index in range(10)]
    parser = MicrosoftSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response(records, 11))
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_microsoft_switzerland_wraps_api_failures() -> None:
    parser = MicrosoftSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_microsoft_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["microsoft_switzerland"]
    assert isinstance(parser, MicrosoftSwitzerlandJobsParser)
    assert parser.base_url == settings.microsoft_switzerland_jobs_base_url
    assert parser.api_url == settings.microsoft_switzerland_jobs_api_url
    assert parser.detail_api_url == settings.microsoft_switzerland_jobs_detail_api_url
    assert parser.max_pages == settings.microsoft_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.microsoft_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Microsoft Switzerland", "filters": {}},
            "sources": ["microsoft_switzerland", "microsoft_switzerland"],
        }
    )
    assert request.sources == ["microsoft_switzerland"]


def test_microsoft_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = MicrosoftSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy(1000, "Software Engineer"))
    stored = parsed_job_to_stored_job(
        job,
        job_id="microsoft_switzerland-1000",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Microsoft Switzerland import"
    assert stored["id"] == "microsoft_switzerland-1000"
