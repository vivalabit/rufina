from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bms_switzerland import (
    BMS_LOCATION,
    BmsSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(
    index: int,
    *,
    multi_location: bool = False,
) -> dict[str, object]:
    job_id = 137482241800 + index
    req_id = f"R160{4600 + index}"
    locations = ["Boudry - CH"]
    standardized = ["Boudry, NE, CH"]
    if multi_location:
        locations = ["Madison - Giralda - NJ - US", "Boudry - CH", "Dublin - IE"]
        standardized = ["Madison, NJ, US", "Boudry, NE, CH", "Dublin, D, IE"]
    return {
        "id": job_id,
        "displayJobId": req_id,
        "name": f"BMS role {index}",
        "locations": locations,
        "standardizedLocations": standardized,
        "postedTs": 1784592000,
        "department": "Quality",
        "creationTs": 1784505600,
        "workLocationOption": "onsite",
        "atsJobId": req_id,
        "positionUrl": f"/careers/job/{job_id}",
    }


def listing_response(
    records: list[dict[str, object]],
    total: int,
) -> dict[str, object]:
    return {
        "status": 200,
        "error": {"message": "", "body": ""},
        "data": {
            "positions": records,
            "count": total,
            "sortBy": "distance",
            "appliedFilters": {
                "includeRemote": ["1"],
                "includeRelocation": ["0"],
            },
        },
        "metadata": None,
    }


def detail_response(
    record: dict[str, object],
    *,
    apply_host: str = "bristolmyerssquibb.wd5.myworkdayjobs.com",
) -> dict[str, object]:
    req_id = record["atsJobId"]
    job_id = record["id"]
    data = {
        **record,
        "jobDescription": (
            "<p><b>Working with Us</b><br>Transform patients' lives.</p>"
            "<ul><li>Build reliable systems.</li></ul>"
        ),
        "location": record["locations"][0],  # type: ignore[index]
        "publicUrl": f"https://jobs.bms.test/careers/job/{job_id}",
        "jdHighlight": [],
        "positionExtraDetails": {"blogs": [{"title": "Marketing"}]},
        "positionUserActions": {
            "isSaved": False,
            "applyAction": {
                "status": "link_off",
                "applyUrl": (
                    f"https://{apply_host}/BMS/job/Boudry---CH/"
                    f"BMS-role-{job_id}_{req_id}/apply?source=Eightfold&utm_campaign="
                ),
            },
        },
    }
    return {
        "status": 200,
        "error": {"message": "", "body": ""},
        "data": data,
        "metadata": None,
    }


def parser_with(
    transport: httpx.BaseTransport,
    **kwargs: object,
) -> BmsSwitzerlandJobsParser:
    return BmsSwitzerlandJobsParser(
        base_url="https://jobs.bms.test/careers",
        api_url="https://jobs.bms.test/api/pcsx/search",
        detail_api_url="https://jobs.bms.test/api/pcsx/position_details",
        detail_workers=1,
        transport=transport,
        **kwargs,
    )


def test_bms_switzerland_scans_every_page_and_enriches_jobs() -> None:
    records = [vacancy(index) for index in range(11)]
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

    result = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert result.status == "completed"
    assert result.message == (
        "Scanned 11 verified BMS Switzerland vacancies from 11 Eightfold records "
        "across 2 page requests"
    )
    assert len(result.jobs) == 11
    listing_requests = [request for request in requests if request.url.path.endswith("/search")]
    detail_requests = [
        request for request in requests if request.url.path.endswith("/position_details")
    ]
    assert [request.url.params["start"] for request in listing_requests] == ["0", "10"]
    assert len(detail_requests) == 11
    assert listing_requests[0].url.params["domain"] == "bms.com"
    assert listing_requests[0].url.params["location"] == BMS_LOCATION
    assert listing_requests[0].url.params["sort_by"] == "distance"
    assert listing_requests[0].url.params["filter_include_remote"] == "1"
    assert listing_requests[0].url.params["filter_include_relocation"] == "0"
    assert "pid" not in listing_requests[0].url.params
    assert detail_requests[0].url.params["queried_location"] == "Switzerland"

    first = result.jobs[0]
    assert first.source == "bms_switzerland"
    assert first.title == "BMS role 0"
    assert first.company == "Bristol Myers Squibb"
    assert first.location == "Boudry, NE, Switzerland"
    assert first.url == "https://jobs.bms.test/careers/job/137482241800"
    assert first.apply_url == (
        "https://bristolmyerssquibb.wd5.myworkdayjobs.com/BMS/job/Boudry---CH/"
        "BMS-role-137482241800_R1604600/apply?source=Eightfold&utm_campaign="
    )
    assert first.posted_at == "2026-07-21T00:00:00Z"
    assert first.description == (
        "Working with Us\nTransform patients' lives.\n• Build reliable systems."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 11
    assert first.raw["detail"]["raw_fields_removed"] == [
        "positionExtraDetails",
        "jdHighlight",
    ]
    assert "positionExtraDetails" not in first.raw["detail"]
    assert result.jobs[-1].raw["listing_offset"] == 10


def test_bms_switzerland_keeps_only_swiss_multi_locations() -> None:
    record = vacancy(1, multi_location=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail_response(record))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs[0].location == "Boudry, NE, Switzerland"
    assert "Madison" not in result.jobs[0].location
    assert "Dublin" not in result.jobs[0].location


def test_bms_switzerland_keeps_listing_when_detail_fails() -> None:
    record = vacancy(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].description is None
    assert result.jobs[0].apply_url == result.jobs[0].url
    assert "503 Service Unavailable" in result.jobs[0].raw["detail_error"]


def test_bms_switzerland_reconciles_a_shifted_catalog() -> None:
    records = [vacancy(index) for index in range(11)]
    listing_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_calls
        if request.url.path.endswith("/search"):
            listing_calls += 1
            offset = int(request.url.params["start"])
            page = records[offset : offset + 10]
            if listing_calls == 2:
                page = [records[9]]
            return httpx.Response(200, json=listing_response(page, len(records)))
        job_id = int(request.url.params["position_id"])
        record = next(item for item in records if item["id"] == job_id)
        return httpx.Response(200, json=detail_response(record))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 11
    assert listing_calls == 4
    assert all(job.raw["listing_pass"] == 2 for job in result.jobs)


@pytest.mark.parametrize(
    "payload,match",
    [
        ([], "invalid status"),
        ({"status": 500, "data": {}}, "invalid status"),
        ({"status": 200, "data": {"count": "1", "positions": []}}, "invalid total"),
        ({"status": 200, "data": {"count": 1, "positions": {}}}, "invalid positions"),
    ],
)
def test_bms_switzerland_rejects_invalid_catalogs(
    payload: object,
    match: str,
) -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser.search(LinkedInSearchRequest())


def test_bms_switzerland_rejects_foreign_catalog_record() -> None:
    record = vacancy(1)
    record["locations"] = ["Dublin - IE"]
    record["standardizedLocations"] = ["Dublin, D, IE"]
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing_response([record], 1)))
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        parser.search(LinkedInSearchRequest())


def test_bms_switzerland_rejects_duplicates_after_catalog_passes() -> None:
    record = vacancy(1)
    parser = parser_with(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response([record, record], 2))
        ),
        max_catalog_passes=2,
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        parser.search(LinkedInSearchRequest())


def test_bms_switzerland_enforces_page_limit() -> None:
    records = [vacancy(index) for index in range(10)]
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing_response(records, 11))),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_bms_switzerland_preserves_listing_for_untrusted_apply_url() -> None:
    record = vacancy(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, json=detail_response(record, apply_host="evil.example"))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].apply_url == result.jobs[0].url
    assert "detail" not in result.jobs[0].raw
    assert "incomplete or mismatched" in result.jobs[0].raw["detail_error"]


def test_bms_switzerland_wraps_api_failures() -> None:
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable")))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bms_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bms_switzerland"]
    assert isinstance(parser, BmsSwitzerlandJobsParser)
    assert parser.base_url == settings.bms_switzerland_jobs_base_url
    assert parser.api_url == settings.bms_switzerland_jobs_api_url
    assert parser.detail_api_url == settings.bms_switzerland_jobs_detail_api_url
    assert parser.max_pages == settings.bms_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.bms_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.bms_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "BMS Switzerland", "filters": {}},
            "sources": ["bms_switzerland", "bms_switzerland"],
        }
    )
    assert request.sources == ["bms_switzerland"]


def test_bms_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = BmsSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="bms_switzerland-137482241801",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bristol Myers Squibb Switzerland import"
    assert stored["company"] == "Bristol Myers Squibb"
