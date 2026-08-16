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
from app.services.parsers.companies.bayer_switzerland import (
    BAYER_JOB_TYPES,
    BAYER_LOCATION,
    BayerSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(
    job_id: int, title: str, *, location: str = "Muttenz,Basel-Country,Switzerland"
) -> dict[str, object]:
    return {
        "id": job_id,
        "name": title,
        "posting_name": title,
        "location": location,
        "locations": [location],
        "hot": 0,
        "department": "Engineering & Technology",
        "business_unit": "Crop Science",
        "t_update": 1785691796,
        "t_create": 1785456000,
        "ats_job_id": str(job_id - 562949900000000),
        "display_job_id": str(job_id - 562949900000000),
        "type": "ATS",
        "id_locale": f"{job_id}-en_US",
        "job_description": "",
        "locale": "en_US",
        "work_location_option": "onsite",
        "canonicalPositionUrl": f"https://talent.bayer.test/careers/job/{job_id}",
        "isPrivate": False,
    }


def listing_response(records: list[dict[str, object]], total: int) -> dict[str, object]:
    return {
        "domain": "bayer.com",
        "positions": records,
        "count": total,
        "location_used": "Switzerland",
        "query": {
            "query": "",
            "location": "Switzerland",
            "pid": "",
            "job type": list(BAYER_JOB_TYPES),
        },
        "isSubQuery": True,
    }


def detail_html(record: dict[str, object], *, country: str = "CH") -> str:
    job_id = record["id"]
    canonical = f"https://talent.bayer.test/careers/job/{job_id}-plant-engineer?domain=bayer.com"
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": record["name"],
        "description": "Help Bayer build reliable production systems.\n\nYour tasks matter.",
        "datePosted": "2026-08-01T00:00:00Z",
        "validThrough": "2026-09-30T23:59:59Z",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "Bayer"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Muttenz",
                "addressRegion": "Basel-Country,CH",
                "addressCountry": {"@type": "Country", "name": country},
            },
        },
        "url": canonical,
    }
    return (
        "<html><head>"
        f'<link rel="canonical" href="{canonical}">'
        f'<script type="application/ld+json">{json.dumps(schema)}</script>'
        "</head><body></body></html>"
    )


def parser_with(
    handler: httpx.MockTransport | object, **kwargs: object
) -> BayerSwitzerlandJobsParser:
    return BayerSwitzerlandJobsParser(
        base_url="https://talent.bayer.test/careers",
        api_url="https://talent.bayer.test/api/apply/v2/jobs",
        detail_workers=1,
        transport=handler,  # type: ignore[arg-type]
        **kwargs,
    )


def test_bayer_switzerland_scans_every_page_and_enriches_jobs() -> None:
    records = [vacancy(562949978000000 + index, f"Bayer role {index}") for index in range(11)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/jobs"):
            offset = int(request.url.params["start"])
            return httpx.Response(
                200,
                json=listing_response(records[offset : offset + 10], len(records)),
            )
        job_id = int(request.url.path.split("/")[-1])
        record = next(item for item in records if item["id"] == job_id)
        return httpx.Response(200, text=detail_html(record))

    parser = parser_with(httpx.MockTransport(handler))
    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 11 Bayer Switzerland vacancies across 2 API pages (11 listed)"
    )
    assert len(result.jobs) == 11
    listing_requests = [request for request in requests if request.url.path.endswith("/jobs")]
    assert [request.url.params["start"] for request in listing_requests] == ["0", "10"]
    assert listing_requests[0].url.params["num"] == "10"
    assert listing_requests[0].url.params["domain"] == "bayer.com"
    assert listing_requests[0].url.params["location"] == BAYER_LOCATION
    assert listing_requests[0].url.params.get_list("job type") == list(BAYER_JOB_TYPES)
    assert "pid" not in listing_requests[0].url.params

    first = result.jobs[0]
    assert first.source == "bayer_switzerland"
    assert first.title == "Bayer role 0"
    assert first.company == "Bayer"
    assert first.location == "Muttenz, Basel-Country, Switzerland"
    assert first.url == (
        "https://talent.bayer.test/careers/job/562949978000000-plant-engineer?domain=bayer.com"
    )
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-01"
    assert first.employment_type == "Full-time"
    assert first.description == (
        "Help Bayer build reliable production systems.\n\nYour tasks matter."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 11
    assert first.raw["detail"]["valid_through"] == "2026-09-30"
    assert result.jobs[-1].raw["listing_offset"] == 10


def test_bayer_switzerland_reconciles_a_shifted_catalog() -> None:
    records = [vacancy(562949978000000 + index, f"Role {index}") for index in range(11)]
    listing_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_calls
        if request.url.path.endswith("/jobs"):
            listing_calls += 1
            offset = int(request.url.params["start"])
            page = records[offset : offset + 10]
            if listing_calls == 2:
                page = [records[9]]
            return httpx.Response(200, json=listing_response(page, len(records)))
        job_id = int(request.url.path.split("/")[-1])
        record = next(item for item in records if item["id"] == job_id)
        return httpx.Response(200, text=detail_html(record))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 11
    assert listing_calls == 4
    assert all(job.raw["listing_pass"] == 2 for job in result.jobs)


def test_bayer_switzerland_keeps_listing_when_detail_fails() -> None:
    record = vacancy(562949978313882, "Plant Engineer")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].url == "https://talent.bayer.test/careers/job/562949978313882"
    assert result.jobs[0].posted_at == "2026-07-31"
    assert result.jobs[0].description is None
    assert "503 Service Unavailable" in result.jobs[0].raw["detail_error"]


def test_bayer_switzerland_keeps_only_swiss_locations_from_a_multi_location_role() -> None:
    record = vacancy(562949978313882, "Plant Engineer", location="Berlin,BE,Germany")
    record["locations"] = ["Berlin,BE,Germany", "Basel,Basel-City,Switzerland"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(503, text="temporarily unavailable")

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs[0].location == "Basel, Basel-City, Switzerland"


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: [], "must be an object"),
        (lambda payload: {**payload, "count": "1"}, "invalid count"),
        (lambda payload: {**payload, "positions": {}}, "invalid positions"),
        (
            lambda payload: {**payload, "location_used": "Germany"},
            "unexpected query metadata",
        ),
        (
            lambda payload: {
                **payload,
                "positions": [vacancy(562949978313882, "Role", location="Berlin,BE,Germany")],
            },
            "invalid vacancy",
        ),
    ],
)
def test_bayer_switzerland_rejects_invalid_catalogs(mutate: object, match: str) -> None:
    payload = listing_response([vacancy(562949978313882, "Role")], 1)
    invalid = mutate(payload)  # type: ignore[operator]
    parser = parser_with(httpx.MockTransport(lambda _: httpx.Response(200, json=invalid)))

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser.search(LinkedInSearchRequest())


def test_bayer_switzerland_rejects_duplicates_after_catalog_passes() -> None:
    record = vacancy(562949978313882, "Role")
    parser = parser_with(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_response([record, record], 2))
        ),
        max_catalog_passes=2,
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        parser.search(LinkedInSearchRequest())


def test_bayer_switzerland_enforces_page_limit() -> None:
    records = [vacancy(562949978000000 + index, f"Role {index}") for index in range(10)]
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing_response(records, 11))),
        max_pages=1,
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize("country", ["DE", "Switzerland", ""])
def test_bayer_switzerland_preserves_listing_when_detail_is_not_strictly_swiss(
    country: str,
) -> None:
    record = vacancy(562949978313882, "Plant Engineer")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=listing_response([record], 1))
        return httpx.Response(200, text=detail_html(record, country=country))

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert "detail" not in result.jobs[0].raw
    assert "incomplete or mismatched" in result.jobs[0].raw["detail_error"]


def test_bayer_switzerland_wraps_api_failures() -> None:
    parser = parser_with(
        httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bayer_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bayer_switzerland"]
    assert isinstance(parser, BayerSwitzerlandJobsParser)
    assert parser.base_url == settings.bayer_switzerland_jobs_base_url
    assert parser.api_url == settings.bayer_switzerland_jobs_api_url
    assert parser.max_pages == settings.bayer_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.bayer_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.bayer_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bayer Switzerland", "filters": {}},
            "sources": ["bayer_switzerland", "bayer_switzerland"],
        }
    )
    assert request.sources == ["bayer_switzerland"]


def test_bayer_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = BayerSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy(562949978313882, "Plant Engineer"))
    stored = parsed_job_to_stored_job(
        job,
        job_id="bayer_switzerland-562949978313882",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bayer Switzerland import"
    assert stored["company"] == "Bayer"
