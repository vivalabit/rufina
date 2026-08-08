from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.abb_switzerland import (
    AbbSwitzerlandJobsParser,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    index: int,
    *,
    country: str = "Switzerland",
    multi_locations: list[str] | None = None,
) -> dict[str, object]:
    job_id = f"JR0004{index:04d}"
    city = "Baden" if country == "Switzerland" else "Mannheim"
    return {
        "contractType": "Regular",
        "type": "Full Time",
        "descriptionTeaser": f"Short description for ABB vacancy {index}.",
        "state": "Aargau" if country == "Switzerland" else "Baden-Wurttemberg",
        "reqId": job_id,
        "city": city,
        "multi_location": multi_locations or [],
        "address": f"{city}, {country}",
        "applyUrl": (
            "https://abb.wd3.myworkdayjobs.com/External_Career_Page/job/"
            f"{city}/Service-Engineer-{index}_{job_id}/apply"
        ),
        "country": country,
        "jobId": job_id,
        "locale": "en_GLOBAL",
        "title": f"Service Engineer {index}",
        "jobSeqNo": f"ABB1GLOBAL{job_id}EXTERNALENGLOBAL",
        "postedDate": "2026-08-08T00:00:00.000+0000",
        "cityStateCountry": f"{city}, {country}",
        "category": "Service",
        "workExperience": "Experienced",
    }


def detail_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "companyName": "ABB",
        "description": (
            "<p>Build reliable power systems.</p><ul><li><p>Support customers.</p></li></ul>"
        ),
        "structureData": {
            "@type": "JobPosting",
            "datePosted": record["postedDate"],
            "employmentType": record["type"],
        },
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


def bootstrap_html(*, csrf_token: str = "test-csrf-token") -> str:
    return (
        "<html><head><script>var phApp = {}; phApp.sessionParams = "
        f'{{"csrfToken":"{csrf_token}"}};'
        "</script></head></html>"
    )


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int,
) -> dict[str, object]:
    return {
        "refineSearch": {
            "status": 200,
            "hits": len(records),
            "totalHits": total,
            "data": {
                "jobs": records,
                "ui_selections": {"country": ["Switzerland"]},
            },
        }
    }


def detail_html(record: dict[str, object]) -> str:
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
            f"https://careers.abb.test/global/en/job/{record['jobId']}/"
            f"Service-Engineer-{record['jobId']}"
        ),
    )


def test_abb_switzerland_fetches_all_pages_and_filters_swiss_locations() -> None:
    records = [listing_record(index) for index in range(11)]
    records.append(listing_record(11, country="Germany"))
    requested_offsets: list[int] = []
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            assert request.url.params["rk"] == "l-abb-switzerland-careers"
            assert request.url.params["sortBy"] == "Most relevant"
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            assert request.method == "POST"
            assert request.headers["x-csrf-token"] == "test-csrf-token"
            payload = json.loads(request.content)
            assert payload["selected_fields"] == {"country": ["Switzerland"]}
            assert payload["size"] == 10
            offset = int(payload["from"])
            requested_offsets.append(offset)
            return httpx.Response(
                200,
                json=listing_payload(records[offset : offset + 10], total=len(records)),
            )
        requested_details.append(request.url.path)
        job_id = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobId"] == job_id)
        return httpx.Response(200, text=detail_html(record))

    parser = AbbSwitzerlandJobsParser(
        base_url=(
            "https://careers.abb.test/global/en/search-results?"
            "rk=l-abb-switzerland-careers&sortBy=Most%20relevant"
        ),
        page_workers=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert sorted(requested_offsets) == [0, 10]
    assert len(requested_details) == 11
    assert result.status == "completed"
    assert result.message == (
        "Scanned 11 ABB Switzerland vacancies from 12 catalog records across 2 page requests"
    )
    assert len(result.jobs) == 11
    first = result.jobs[0]
    assert first.source == "abb_switzerland"
    assert first.title == "Service Engineer 0"
    assert first.company == "ABB"
    assert first.location == "Baden, Switzerland"
    assert first.url == (
        "https://careers.abb.test/global/en/job/JR00040000/Service-Engineer-JR00040000"
    )
    assert first.apply_url == (
        "https://abb.wd3.myworkdayjobs.com/External_Career_Page/job/"
        "Baden/Service-Engineer-0_JR00040000/apply"
    )
    assert first.posted_at == "2026-08-08T00:00:00.000+0000"
    assert first.employment_type == "Full Time"
    assert first.seniority == "Experienced"
    assert first.description == "Build reliable power systems.\n- Support customers."
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 12


def test_abb_switzerland_includes_swiss_multi_location_roles() -> None:
    record = listing_record(
        1,
        country="Italy",
        multi_locations=[
            "Sesto San Giovanni, Milano, Italy",
            "Zurich, Zurich, Switzerland",
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            return httpx.Response(200, json=listing_payload([record], total=1))
        detail = detail_record(record)
        detail["multi_location"] = [
            {"location": "Sesto San Giovanni, Milano, Italy"},
            {"location": "Zurich, Zurich, Switzerland"},
        ]
        return httpx.Response(
            200,
            text=ddo_html(
                {
                    "jobDetail": {
                        "status": 200,
                        "data": {"job": detail},
                    }
                }
            ),
        )

    parser = AbbSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler),
        detail_workers=1,
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Zurich, Zurich, Switzerland"


def test_abb_switzerland_repeats_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(12)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            offset = int(json.loads(request.content)["from"])
            requested_offsets.append(offset)
            if offset == 0:
                page_records = records[:10]
            elif requested_offsets.count(10) == 1:
                page_records = [records[9], records[10]]
            else:
                page_records = records[10:]
            return httpx.Response(
                200,
                json=listing_payload(page_records, total=len(records)),
            )
        job_id = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobId"] == job_id)
        return httpx.Response(200, text=detail_html(record))

    parser = AbbSwitzerlandJobsParser(
        max_catalog_passes=2,
        page_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert sorted(requested_offsets) == [0, 0, 10, 10]
    assert len(result.jobs) == 12


def test_abb_switzerland_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            return httpx.Response(200, json=listing_payload([record], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = AbbSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler),
        detail_workers=1,
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.description == "Short description for ABB vacancy 1."
    assert job.url.endswith("/global/en/job/JR00040001")
    assert job.apply_url == record["applyUrl"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_abb_switzerland_rejects_invalid_catalog_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(
            200,
            json={
                "refineSearch": {
                    "status": 200,
                    "hits": 1,
                    "totalHits": 1,
                    "data": {"jobs": {}},
                }
            },
        )

    parser = AbbSwitzerlandJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_abb_switzerland_does_not_silently_truncate_above_page_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(
            200,
            json=listing_payload(
                [listing_record(index) for index in range(10)],
                total=21,
            ),
        )

    parser = AbbSwitzerlandJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_abb_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["abb_switzerland"]
    assert isinstance(parser, AbbSwitzerlandJobsParser)
    assert parser.base_url == settings.abb_switzerland_jobs_base_url
    assert parser.max_pages == settings.abb_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.abb_switzerland_jobs_max_catalog_passes
    assert parser.page_workers == settings.abb_switzerland_jobs_page_workers
    assert parser.detail_workers == settings.abb_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ABB Schweiz", "filters": {}},
            "sources": ["abb_switzerland", "abb_switzerland"],
        }
    )
    assert request.sources == ["abb_switzerland"]


def test_abb_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = AbbSwitzerlandJobsParser()
    stored = parsed_job_to_stored_job(
        parser.normalize_job(listing_record(1)),
        job_id="abb_switzerland-JR00040001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "ABB Schweiz import"
    assert stored["id"] == "abb_switzerland-JR00040001"
