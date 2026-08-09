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
from app.services.parsers.companies.msd import MsdJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    index: int,
    *,
    primary_country: str = "Switzerland",
) -> dict[str, object]:
    job_id = f"R40{index:04d}"
    primary_location = (
        "West Point, Pennsylvania, United States of America"
        if primary_country != "Switzerland"
        else "Lucerne, Lucerne, Switzerland"
    )
    multi_locations = [primary_location]
    if primary_country != "Switzerland":
        multi_locations.append("Schachen, Lucerne, Switzerland")
    return {
        "type": "Full time",
        "descriptionTeaser": f"Short MSD description {index}.",
        "state": "Pennsylvania" if primary_country != "Switzerland" else "Lucerne",
        "reqId": job_id,
        "city": "West Point" if primary_country != "Switzerland" else "Lucerne",
        "multi_location": multi_locations,
        "address": primary_location,
        "applyUrl": f"https://msd.wd5.test/SearchJobs/{job_id}/apply",
        "country": primary_country,
        "jobId": job_id,
        "locale": "en_GB",
        "title": f"Clinical Supply Specialist {index}",
        "jobSeqNo": f"MSD1GB{job_id}ENGB",
        "postedDate": "2026-08-08T00:00:00.000+0000",
        "cityStateCountry": primary_location,
        "location": primary_location,
        "category": "Manufacturing & Quality Assurance",
        "jobProfile": "Experienced Professional",
    }


def detail_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "companyName": "MSD",
        "description": (
            "<p>Advance pharmaceutical supply.</p>"
            "<ul><li><p>Coordinate global teams.</p></li></ul>"
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


def bootstrap_html(*, csrf_token: str = "msd-csrf-token") -> str:
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
            f"https://jobs.msd.test/gb/en/job/{record['jobId']}/"
            f"Clinical-Supply-Specialist-{record['jobId']}"
        ),
    )


def test_msd_fetches_all_swiss_pages_and_enriches_details() -> None:
    records = [
        listing_record(index, primary_country="United States of America" if index == 0 else "Switzerland")
        for index in range(12)
    ]
    requested_offsets: list[int] = []
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gb/en/search-results":
            assert request.url.params["rk"] == "page-targeted-jobs-page172-prod-DZJ1ve"
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            assert request.method == "POST"
            assert request.headers["x-csrf-token"] == "msd-csrf-token"
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
        job_sequence = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == job_sequence)
        return httpx.Response(200, text=detail_html(record))

    parser = MsdJobsParser(
        base_url=(
            "https://jobs.msd.test/gb/en/search-results?"
            "rk=page-targeted-jobs-page172-prod-DZJ1ve"
        ),
        page_workers=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert sorted(requested_offsets) == [0, 10]
    assert len(requested_details) == 12
    assert result.status == "completed"
    assert result.message == (
        "Scanned 12 MSD Switzerland vacancies across 2 Phenom page requests"
    )
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "msd"
    assert first.title == "Clinical Supply Specialist 0"
    assert first.company == "MSD"
    assert first.location == "Schachen, Lucerne, Switzerland"
    assert first.url == (
        "https://jobs.msd.test/gb/en/job/R400000/"
        "Clinical-Supply-Specialist-R400000"
    )
    assert first.apply_url == "https://msd.wd5.test/SearchJobs/R400000/apply"
    assert first.posted_at == "2026-08-08T00:00:00.000+0000"
    assert first.employment_type == "Full time"
    assert first.seniority == "Experienced Professional"
    assert first.description == (
        "Advance pharmaceutical supply.\n- Coordinate global teams."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 12


def test_msd_repeats_shifted_pages_until_one_complete_snapshot_is_seen() -> None:
    records = [listing_record(index) for index in range(12)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gb/en/search-results":
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

    parser = MsdJobsParser(
        max_catalog_passes=2,
        page_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 10, 0, 10]
    assert len(result.jobs) == 12
    assert {job.raw["listing_pass"] for job in result.jobs} == {1}


def test_msd_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gb/en/search-results":
            return httpx.Response(200, text=bootstrap_html())
        if request.url.path == "/widgets":
            return httpx.Response(200, json=listing_payload([record], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = MsdJobsParser(
        transport=httpx.MockTransport(handler),
        detail_workers=1,
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.description == "Short MSD description 1."
    assert job.url.endswith(f"/gb/en/job/{record['jobSeqNo']}")
    assert job.apply_url == record["applyUrl"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_msd_rejects_invalid_catalog_or_non_swiss_targeted_record() -> None:
    invalid_catalog = MsdJobsParser(
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
    non_swiss["cityStateCountry"] = "Munich, Bavaria, Germany"
    non_swiss["location"] = "Munich, Bavaria, Germany"
    non_swiss["address"] = "Munich, Bavaria, Germany"
    non_swiss["multi_location"] = ["Munich, Bavaria, Germany"]

    def non_swiss_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(200, json=listing_payload([non_swiss], total=1))

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        invalid_catalog.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="0 Swiss vacancies of 1"):
        MsdJobsParser(
            transport=httpx.MockTransport(non_swiss_handler)
        ).search(LinkedInSearchRequest())


def test_msd_does_not_silently_truncate_above_page_limit() -> None:
    records = [listing_record(index) for index in range(10)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=bootstrap_html())
        return httpx.Response(200, json=listing_payload(records, total=21))

    parser = MsdJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_msd_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["msd"]
    assert isinstance(parser, MsdJobsParser)
    assert parser.base_url == settings.msd_jobs_base_url
    assert parser.max_pages == settings.msd_jobs_max_pages
    assert parser.max_catalog_passes == settings.msd_jobs_max_catalog_passes
    assert parser.page_workers == settings.msd_jobs_page_workers
    assert parser.detail_workers == settings.msd_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "MSD", "filters": {}},
            "sources": ["msd", "msd"],
        }
    )
    assert request.sources == ["msd"]


def test_msd_jobs_render_as_direct_company_imports() -> None:
    parser = MsdJobsParser()
    stored = parsed_job_to_stored_job(
        parser.normalize_job(listing_record(1)),
        job_id="msd-r400001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "MSD import"
    assert stored["id"] == "msd-r400001"
