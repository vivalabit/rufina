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
from app.services.parsers.companies.roche_switzerland import (
    RocheSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    index: int,
    *,
    primary_country: str = "Switzerland",
) -> dict[str, object]:
    job_id = f"202608-{108000 + index}"
    primary_location = (
        "Mannheim, Baden-Wurttemberg, Germany"
        if primary_country != "Switzerland"
        else "Basel, Basel-City, Switzerland"
    )
    multi_locations = [primary_location]
    if primary_country != "Switzerland":
        multi_locations.append("Kaiseraugst, Aargau, Switzerland")
    return {
        "type": "Full time",
        "descriptionTeaser": f"Short Roche description {index}.",
        "state": "Basel-City",
        "reqId": job_id,
        "city": "Basel",
        "multi_location": multi_locations,
        "address": primary_location,
        "applyUrl": f"https://roche.wd3.test/roche-ext/{job_id}/apply",
        "country": primary_country,
        "jobId": job_id,
        "locale": "en_GLOBAL",
        "title": f"Computational Scientist {index}",
        "jobSeqNo": f"ROCHGLOBAL{job_id.replace('-', '')}EXTERNALENGLOBAL",
        "postedDate": "2026-08-08T00:00:00.000+0000",
        "cityStateCountry": primary_location,
        "location": primary_location,
        "category": "Research & Development",
        "jobLevel": "Individual Contributor",
    }


def detail_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "companyName": "Roche",
        "standardisedCountry": "Switzerland",
        "additionalFields": {"jobLevel": "Individual Contributor"},
        "structureData": {
            "datePosted": "2026-08-08",
            "employmentType": "Full time",
            "description": (
                "<p>Advance computational medicine.</p>"
                "<ul><li><p>Collaborate across research teams.</p></li></ul>"
            ),
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


def bootstrap_html(*, csrf_token: str = "roche-csrf-token") -> str:
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
            "data": {"jobs": records},
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
            f"https://careers.roche.test/global/en/job/{record['jobSeqNo']}/"
            f"Computational-Scientist-{record['jobId']}"
        ),
    )


def test_roche_fetches_all_swiss_pages_and_enriches_details() -> None:
    records = [
        listing_record(
            index,
            primary_country="Germany" if index == 0 else "Switzerland",
        )
        for index in range(12)
    ]
    requested_offsets: list[int] = []
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            assert request.method == "POST"
            assert request.headers["x-csrf-token"] == "roche-csrf-token"
            payload = json.loads(request.content)
            assert payload["selected_fields"] == {"country": ["Switzerland"]}
            assert payload["all_fields"] == [
                "category",
                "subCategory",
                "country",
                "state",
                "city",
                "type",
                "jobLevel",
                "jobType",
            ]
            assert payload["size"] == 10
            offset = int(payload["from"])
            requested_offsets.append(offset)
            return httpx.Response(
                200,
                json=listing_payload(records[offset : offset + 10], total=len(records)),
            )
        requested_details.append(request.url.path)
        job_sequence = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == job_sequence)
        return httpx.Response(200, text=detail_html(record))

    parser = RocheSwitzerlandJobsParser(
        base_url="https://careers.roche.test/global/en/search-results",
        page_workers=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert sorted(requested_offsets) == [0, 10]
    assert len(requested_details) == 12
    assert result.status == "completed"
    assert result.message == (
        "Scanned 12 Roche Switzerland vacancies across 2 Phenom page requests"
    )
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "roche_switzerland"
    assert first.title == "Computational Scientist 0"
    assert first.company == "Roche"
    assert first.location == "Kaiseraugst, Aargau, Switzerland"
    assert first.url == (
        f"https://careers.roche.test/global/en/job/{records[0]['jobSeqNo']}/"
        f"Computational-Scientist-{records[0]['jobId']}"
    )
    assert first.apply_url == records[0]["applyUrl"]
    assert first.posted_at == "2026-08-08"
    assert first.employment_type == "Full time"
    assert first.seniority == "Individual Contributor"
    assert first.description == (
        "Advance computational medicine.\n- Collaborate across research teams."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 12


def test_roche_repeats_shifted_pages_until_complete_snapshot() -> None:
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
        job_sequence = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == job_sequence)
        return httpx.Response(200, text=detail_html(record))

    parser = RocheSwitzerlandJobsParser(
        max_catalog_passes=2,
        page_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 10, 0, 10]
    assert len(result.jobs) == 12
    assert {job.raw["listing_pass"] for job in result.jobs} == {1}


def test_roche_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            return httpx.Response(200, json=listing_payload([record], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = RocheSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler),
        detail_workers=1,
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.description == "Short Roche description 1."
    assert job.url.endswith(f"/global/en/job/{record['jobSeqNo']}")
    assert job.apply_url == record["applyUrl"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_roche_rejects_invalid_or_non_swiss_catalog() -> None:
    invalid_catalog = RocheSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, text=bootstrap_html())
                if request.method == "GET"
                else httpx.Response(
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
            )
        )
    )
    non_swiss = listing_record(1)
    non_swiss["country"] = "Germany"
    non_swiss["cityStateCountry"] = "Mannheim, Baden-Wurttemberg, Germany"
    non_swiss["location"] = "Mannheim, Baden-Wurttemberg, Germany"
    non_swiss["address"] = "Mannheim, Baden-Wurttemberg, Germany"
    non_swiss["multi_location"] = ["Mannheim, Baden-Wurttemberg, Germany"]

    def non_swiss_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(200, json=listing_payload([non_swiss], total=1))

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        invalid_catalog.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="0 Swiss vacancies of 1"):
        RocheSwitzerlandJobsParser(transport=httpx.MockTransport(non_swiss_handler)).search(
            LinkedInSearchRequest()
        )


def test_roche_does_not_silently_truncate_above_page_limit() -> None:
    records = [listing_record(index) for index in range(10)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(200, json=listing_payload(records, total=21))

    parser = RocheSwitzerlandJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_roche_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["roche_switzerland"]
    assert isinstance(parser, RocheSwitzerlandJobsParser)
    assert parser.base_url == settings.roche_switzerland_jobs_base_url
    assert parser.max_pages == settings.roche_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.roche_switzerland_jobs_max_catalog_passes
    assert parser.page_workers == settings.roche_switzerland_jobs_page_workers
    assert parser.detail_workers == settings.roche_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Roche Switzerland", "filters": {}},
            "sources": ["roche_switzerland", "roche_switzerland"],
        }
    )
    assert request.sources == ["roche_switzerland"]


def test_roche_jobs_render_as_direct_company_imports() -> None:
    parser = RocheSwitzerlandJobsParser()
    stored = parsed_job_to_stored_job(
        parser.normalize_job(listing_record(1)),
        job_id="roche_switzerland-202608-108001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Roche Switzerland import"
    assert stored["id"] == "roche_switzerland-202608-108001"
    assert stored["company"] == "Roche"
