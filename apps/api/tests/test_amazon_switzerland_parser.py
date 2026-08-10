from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.amazon_switzerland import (
    AmazonSwitzerlandJobsParser,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    job_id = str(1_040_000 + index)
    location = {
        "normalizedStateName": "Zurich",
        "normalizedCountryCode": "CHE",
        "city": "Zurich",
        "countryIso3a": "CHE",
        "countryIso2a": "CH",
        "locationNonStemming": "Switzerland, ZH, Zurich",
        "normalizedCountryName": "Switzerland",
        "normalizedLocation": "Zurich, Zurich, CHE",
        "location": "CH, ZH, Zurich",
        "region": "ZH",
        "normalizedCityName": "Zurich",
    }
    return {
        "id": f"uuid-{index}",
        "id_icims": job_id,
        "title": f"Cloud Engineer {index}",
        "company_name": "AWS EMEA SARL (Switzerland Branch)",
        "country_code": "CHE",
        "description": (
            "<p>Build reliable cloud platforms.</p>"
            "<ul><li>Automate services</li><li>Support customers</li></ul>"
        ),
        "basic_qualifications": "- Experience with Python<br/>- Fluent English",
        "preferred_qualifications": "<p>AWS certification</p>",
        "job_category": "Software Development",
        "job_path": f"/en/jobs/{job_id}/cloud-engineer-{index}",
        "job_schedule_type": "full-time",
        "location": "CH, ZH, Zurich",
        "locations": [json.dumps(location)],
        "normalized_location": "Zurich, Zurich, CHE",
        "posted_date": "August 10, 2026",
        "url_next_step": f"https://account.amazon.jobs/jobs/{job_id}/apply",
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int,
) -> dict[str, object]:
    return {
        "error": None,
        "hits": total,
        "facets": {},
        "jobs": records,
    }


def test_amazon_fetches_complete_swiss_catalog_and_normalizes_records() -> None:
    records = [listing_record(index) for index in range(101)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/en/search.json"
        assert request.url.params["country"] == "CHE"
        assert request.url.params["result_limit"] == "100"
        assert request.url.params["sort"] == "relevant"
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=listing_payload(records[offset : offset + 100], total=len(records)),
        )

    parser = AmazonSwitzerlandJobsParser(
        base_url="https://www.amazon.jobs/content/en/locations/switzerland/zurich",
        api_url="https://www.amazon.jobs/en/search.json",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 100]
    assert result.status == "completed"
    assert result.search_url.endswith("/locations/switzerland/zurich")
    assert result.message == (
        "Scanned 101 Amazon Switzerland vacancies from 101 catalog records "
        "across 2 API page requests"
    )
    assert len(result.jobs) == 101
    first = result.jobs[0]
    assert first.source == "amazon_switzerland"
    assert first.title == "Cloud Engineer 0"
    assert first.company == "AWS EMEA SARL (Switzerland Branch)"
    assert first.location == "Zurich, ZH, Switzerland"
    assert first.url == "https://www.amazon.jobs/en/jobs/1040000/cloud-engineer-0"
    assert first.apply_url == "https://account.amazon.jobs/jobs/1040000/apply"
    assert first.posted_at == "August 10, 2026"
    assert first.employment_type == "full-time"
    assert first.description == (
        "Description\nBuild reliable cloud platforms.\n- Automate services\n"
        "- Support customers\n\nBasic qualifications\n- Experience with Python\n"
        "- Fluent English\n\nPreferred qualifications\nAWS certification"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 101
    assert first.raw["normalized_job_id"] == "1040000"


def test_amazon_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(101)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        if offset == 0:
            page_records = records[:100]
        elif requested_offsets.count(100) == 1:
            page_records = [records[99]]
        else:
            page_records = records[100:]
        return httpx.Response(
            200,
            json=listing_payload(page_records, total=len(records)),
        )

    parser = AmazonSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 100, 0, 100]
    assert len(result.jobs) == 101
    assert result.message.endswith("across 4 API page requests")


def test_amazon_rejects_invalid_or_non_swiss_payload() -> None:
    invalid = AmazonSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"hits": "one", "jobs": []})
        )
    )
    non_swiss_record = listing_record(1)
    non_swiss_record["country_code"] = "DEU"
    non_swiss = AmazonSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([non_swiss_record], total=1),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid total"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        non_swiss.search(LinkedInSearchRequest())


def test_amazon_enforces_catalog_page_limit() -> None:
    parser = AmazonSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(100)],
                    total=101,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_amazon_wraps_listing_request_failures() -> None:
    parser = AmazonSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_amazon_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["amazon_switzerland"]
    assert isinstance(parser, AmazonSwitzerlandJobsParser)
    assert parser.base_url == settings.amazon_switzerland_jobs_base_url
    assert parser.api_url == settings.amazon_switzerland_jobs_api_url
    assert parser.max_pages == settings.amazon_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.amazon_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Amazon Switzerland", "filters": {}},
            "sources": ["amazon_switzerland", "amazon_switzerland"],
        }
    )
    assert request.sources == ["amazon_switzerland"]


def test_amazon_jobs_render_as_direct_company_imports() -> None:
    parser = AmazonSwitzerlandJobsParser()
    record = listing_record(1)
    record["swiss_locations"] = [json.loads(record["locations"][0])]
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="amazon_switzerland-1040001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Amazon Switzerland import"
    assert stored["id"] == "amazon_switzerland-1040001"
