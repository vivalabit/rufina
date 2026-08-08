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
from app.services.parsers.companies.sunrise import SunriseJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    requisition = f"REQ_3003{index:04d}"
    sequence = f"SCASCAGB{requisition.replace('_', '')}EXTERNALENGB"
    return {
        "type": "Full time",
        "descriptionTeaser": f"Short description for vacancy {index}.",
        "state": "Zurich",
        "reqId": requisition,
        "city": "Glattpark_AmbassadorHouse",
        "address": "Ambassador House, 8152 Glattpark (Opfikon) ZH, Switzerland",
        "applyUrl": (
            "https://sunrise.wd3.myworkdayjobs.com/Sunrise/job/"
            f"Glattpark_AmbassadorHouse/Platform-Engineer-{index}_{requisition}/apply"
        ),
        "country": "Switzerland",
        "jobId": requisition,
        "locale": "en_GB",
        "title": f"Platform Engineer {index}",
        "jobSeqNo": sequence,
        "postedDate": "2026-08-06T00:00:00.000+0000",
        "cityStateCountry": "Glattpark (Opfikon), Zurich, Switzerland",
        "category": "Network & Engineering",
    }


def detail_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "companyName": "Sunrise Communications AG",
        "timeType": "Full time",
        "jobProfile": "Level 4 | Professional | Technology",
        "description": (
            "<p>Build reliable telecom platforms.</p><ul><li>Own production services.</li></ul>"
        ),
    }


def ddo_html(payload: dict[str, object], *, canonical_url: str | None = None) -> str:
    canonical = f'<link rel="canonical" href="{canonical_url}">' if canonical_url else ""
    return (
        "<html><head>"
        f"{canonical}"
        "<script>var phApp = {}; phApp.ddo = "
        f"{json.dumps(payload)}"
        "; phApp.experimentData = {};</script></head></html>"
    )


def listing_html(records: list[dict[str, object]], *, total: int) -> str:
    return ddo_html(
        {
            "eagerLoadRefineSearch": {
                "status": 200,
                "hits": len(records),
                "totalHits": total,
                "data": {"jobs": records},
            }
        }
    )


def detail_html(record: dict[str, object]) -> str:
    sequence = str(record["jobSeqNo"])
    return ddo_html(
        {
            "jobDetail": {
                "status": 200,
                "hits": 1,
                "totalHits": 1,
                "data": {"job": detail_record(record)},
            }
        },
        canonical_url=(
            f"https://careers.sunrise.test/gb/en/job/{sequence}/Platform-Engineer-{record['jobId']}"
        ),
    )


def test_sunrise_fetches_every_page_and_enriches_records() -> None:
    records = [listing_record(index) for index in range(12)]
    requested_offsets: list[int] = []
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/gb/en/search-results":
            assert request.url.params["s"] == "1"
            offset = int(request.url.params["from"])
            requested_offsets.append(offset)
            return httpx.Response(
                200,
                text=listing_html(records[offset : offset + 10], total=len(records)),
            )
        requested_details.append(request.url.path)
        sequence = request.url.path.rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == sequence)
        return httpx.Response(200, text=detail_html(record))

    parser = SunriseJobsParser(
        base_url="https://careers.sunrise.test/gb/en/search-results",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 10]
    assert len(requested_details) == 12
    assert result.status == "completed"
    assert result.message == "Scanned 12 Sunrise vacancies across 2 catalog pages"
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "sunrise"
    assert first.title == "Platform Engineer 0"
    assert first.company == "Sunrise Communications AG"
    assert first.location == "Glattpark (Opfikon), Zurich, Switzerland"
    assert first.url == (
        "https://careers.sunrise.test/gb/en/job/"
        "SCASCAGBREQ30030000EXTERNALENGB/Platform-Engineer-REQ_30030000"
    )
    assert first.apply_url == (
        "https://sunrise.wd3.myworkdayjobs.com/Sunrise/job/"
        "Glattpark_AmbassadorHouse/Platform-Engineer-0_REQ_30030000/apply"
    )
    assert first.posted_at == "2026-08-06T00:00:00.000+0000"
    assert first.employment_type == "Full time"
    assert first.seniority == "Level 4 | Professional | Technology"
    assert first.description == ("Build reliable telecom platforms.\nOwn production services.")
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 12
    assert isinstance(first.raw["detail"], dict)


def test_sunrise_repeats_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(12)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gb/en/search-results":
            offset = int(request.url.params["from"])
            requested_offsets.append(offset)
            if offset == 0:
                page_records = records[:10]
            elif requested_offsets.count(10) == 1:
                page_records = [records[9], records[10]]
            else:
                page_records = records[10:]
            return httpx.Response(
                200,
                text=listing_html(page_records, total=len(records)),
            )
        sequence = request.url.path.rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == sequence)
        return httpx.Response(200, text=detail_html(record))

    parser = SunriseJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 10, 0, 10]
    assert len(result.jobs) == 12


def test_sunrise_preserves_listing_when_a_detail_request_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gb/en/search-results":
            return httpx.Response(200, text=listing_html([record], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = SunriseJobsParser(transport=httpx.MockTransport(handler))

    result = parser.search(LinkedInSearchRequest())

    job = result.jobs[0]
    assert job.description == "Short description for vacancy 1."
    assert job.url.endswith("/job/SCASCAGBREQ30030001EXTERNALENGB")
    assert job.apply_url == record["applyUrl"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_sunrise_rejects_invalid_catalog_payload() -> None:
    parser = SunriseJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=ddo_html(
                    {
                        "eagerLoadRefineSearch": {
                            "status": 200,
                            "hits": 1,
                            "totalHits": 1,
                            "data": {"jobs": {}},
                        }
                    }
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_sunrise_does_not_silently_truncate_above_page_limit() -> None:
    parser = SunriseJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [listing_record(index) for index in range(10)],
                    total=21,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_sunrise_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["sunrise"]
    assert isinstance(parser, SunriseJobsParser)
    assert parser.base_url == settings.sunrise_jobs_base_url
    assert parser.max_catalog_passes == settings.sunrise_jobs_max_catalog_passes
    assert parser.detail_workers == settings.sunrise_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Sunrise", "filters": {}},
            "sources": ["sunrise", "sunrise"],
        }
    )
    assert request.sources == ["sunrise"]


def test_sunrise_jobs_render_as_direct_company_imports() -> None:
    parser = SunriseJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="sunrise-SCASCAGBREQ30030001EXTERNALENGB",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Sunrise import"
    assert stored["id"] == "sunrise-SCASCAGBREQ30030001EXTERNALENGB"
