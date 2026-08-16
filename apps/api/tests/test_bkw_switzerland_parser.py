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
from app.services.parsers.companies.bkw_switzerland import (
    BKW_SWITZERLAND_API_URL,
    BkwSwitzerlandJobsParser,
    normalize_job,
    parse_catalog_payload,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOB_IDS = (
    "974955bb-343b-44e5-bfa9-af77587ef35d",
    "d716df00-4cd8-4f87-88d0-a028e1cc1279",
)


def country_filter() -> dict[str, object]:
    return {
        "filterConfiguration": {
            "filters": [
                {
                    "id": "115",
                    "identifier": "Land",
                    "type": "MultiSelect",
                    "options": [
                        {
                            "id": "116",
                            "title": "Switzerland",
                            "isHeading": False,
                        },
                        {"id": "117", "title": "Germany", "isHeading": False},
                    ],
                }
            ]
        }
    }


def listing_record(
    index: int,
    *,
    category_id: str = "116",
    category_title: str = "Switzerland",
    location_country: str | None = "Schweiz",
) -> dict[str, object]:
    locations: list[dict[str, object]] = []
    if location_country:
        locations.append(
            {
                "id": 755304 + index,
                "title": f"Platform Engineer {index}",
                "type": "location",
                "address": {
                    "city": "Bern" if location_country == "Schweiz" else "Berlin",
                    "country": location_country,
                },
            }
        )
    return {
        "type": "jobs",
        "id": str(7200 + index),
        "title": f"Platform Engineer {index}",
        "url": (f"https://job.bkw.com/offene-stellen/platform-engineer-{index}/{JOB_IDS[index]}"),
        "relations": {
            "Land": [
                {
                    "type": "category",
                    "id": category_id,
                    "title": category_title,
                }
            ],
            "Unternehmen": [{"type": "category", "id": "2547", "title": "BKW Management AG"}],
            "Anstellungsart": [{"type": "category", "id": "2512", "title": "Permanent contract"}],
            "Position": [
                {
                    "type": "category",
                    "id": "2519",
                    "title": "Specialist responsibility",
                }
            ],
        },
        "pensum": {"min": 60, "max": 100},
        "locations": locations,
        "isExternal": True,
    }


def detail_html(
    index: int,
    *,
    country: str = "Schweiz",
    title_suffix: str = "",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": f"Platform Engineer {index}{title_suffix}",
        "description": (
            "<h2>Your impact</h2><p>Build reliable energy platforms.</p>"
            "<ul><li>Improve services</li></ul>"
        ),
        "datePosted": "2026-08-10",
        "validThrough": "2026-09-08",
        "employmentType": "PART_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "BKW Energie AG"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Bern",
                "addressCountry": country,
            },
        },
    }
    apply_url = f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[index]}/ats/"
    return (
        "<html><body>"
        f'<a href="{apply_url}">Apply</a>'
        f'<script type="application/ld+json">{json.dumps(schema)}</script>'
        "</body></html>"
    )


def test_bkw_fetches_complete_swiss_catalog_and_details() -> None:
    records = [listing_record(0), listing_record(1, location_country=None)]
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.bkw.com":
            return httpx.Response(
                200,
                json={"data": records, "meta": country_filter()},
                request=request,
            )
        detail_requests.append(request.url.path)
        index = 1 if JOB_IDS[1] in request.url.path else 0
        return httpx.Response(200, text=detail_html(index), request=request)

    result = BkwSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(detail_requests) == 2
    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 BKW Switzerland vacancies from 2 global BKW catalog records"
    )
    job = result.jobs[0]
    assert job.source == "bkw_switzerland"
    assert job.title == "Platform Engineer 0"
    assert job.company == "BKW Energie AG"
    assert job.location == "Bern, Schweiz"
    assert job.url.endswith(JOB_IDS[0])
    assert job.apply_url == (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[0]}/ats/")
    assert job.posted_at == "2026-08-10"
    assert job.employment_type == "60-100%, Part-time, Permanent contract"
    assert job.seniority == "Specialist responsibility"
    assert job.description == ("Your impact\nBuild reliable energy platforms.\n- Improve services")


def test_bkw_filters_foreign_categories_and_false_swiss_location_matches() -> None:
    records = [
        listing_record(0, category_id="117", category_title="Germany"),
        listing_record(1, location_country="Deutschland"),
    ]
    detail_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_requests
        if request.url.host == "jobs.bkw.com":
            return httpx.Response(
                200,
                json={"data": records, "meta": country_filter()},
                request=request,
            )
        detail_requests += 1
        return httpx.Response(500, request=request)

    result = BkwSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert result.jobs == []
    assert detail_requests == 0


def test_bkw_preserves_safe_listing_when_detail_fails() -> None:
    record = listing_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.bkw.com":
            return httpx.Response(
                200,
                json={"data": [record], "meta": country_filter()},
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        BkwSwitzerlandJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.company == "BKW Management AG"
    assert job.location == "Bern"
    assert job.description is None
    assert job.apply_url.endswith(f"/{JOB_IDS[0]}/ats/")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_bkw_drops_locationless_listing_when_detail_cannot_verify_country() -> None:
    record = listing_record(0, location_country=None)
    record["locations"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.bkw.com":
            return httpx.Response(
                200,
                json={"data": [record], "meta": country_filter()},
                request=request,
            )
        return httpx.Response(503, request=request)

    result = BkwSwitzerlandJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert result.jobs == []


def test_bkw_rejects_changed_detail_identity_or_foreign_schema() -> None:
    url = str(listing_record(0)["url"])
    with pytest.raises(DirectCompanyRequestError, match="incomplete detail"):
        parse_detail_html(
            detail_html(1),
            page_url=url,
            expected_url=url,
            expected_id=JOB_IDS[0],
            expected_title="Platform Engineer 0",
        )
    with pytest.raises(DirectCompanyRequestError, match="incomplete detail"):
        parse_detail_html(
            detail_html(0, country="Deutschland"),
            page_url=url,
            expected_url=url,
            expected_id=JOB_IDS[0],
            expected_title="Platform Engineer 0",
        )


def test_bkw_accepts_official_jobposting_title_suffix() -> None:
    url = str(listing_record(0)["url"])
    detail = parse_detail_html(
        detail_html(0, title_suffix=" - Energy Platforms"),
        page_url=url,
        expected_url=url,
        expected_id=JOB_IDS[0],
        expected_title="Platform Engineer 0",
    )

    assert detail["title"] == "Platform Engineer 0"


def test_bkw_rejects_changed_filter_duplicate_and_oversized_catalogs() -> None:
    valid = listing_record(0)
    duplicate = {**listing_record(1), "url": valid["url"]}
    kwargs = {
        "page_url": BKW_SWITZERLAND_API_URL,
        "expected_url": BKW_SWITZERLAND_API_URL,
        "max_jobs": 10,
    }
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parse_catalog_payload({"data": [valid, duplicate], "meta": country_filter()}, **kwargs)
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parse_catalog_payload(
            {"data": [valid, listing_record(1)], "meta": country_filter()},
            **{**kwargs, "max_jobs": 1},
        )
    changed_meta = country_filter()
    changed_meta["filterConfiguration"]["filters"][0]["options"][0]["id"] = "new"  # type: ignore[index]
    with pytest.raises(DirectCompanyRequestError, match="Switzerland category"):
        parse_catalog_payload({"data": [valid], "meta": changed_meta}, **kwargs)


def test_bkw_wraps_catalog_request_failures() -> None:
    parser = BkwSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="BKW Switzerland vacancy request"):
        parser.search(LinkedInSearchRequest())


def test_bkw_is_registered_and_jobs_render_as_direct_company_imports() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["bkw_switzerland"]

    assert isinstance(parser, BkwSwitzerlandJobsParser)
    assert parser.base_url == settings.bkw_switzerland_jobs_base_url
    assert parser.api_url == settings.bkw_switzerland_jobs_api_url
    assert parser.max_jobs == settings.bkw_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.bkw_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "BKW", "filters": {}},
            "sources": ["bkw_switzerland", "bkw_switzerland"],
        }
    )
    assert request.sources == ["bkw_switzerland"]

    record = listing_record(0)
    record["detail"] = {
        "title": "Platform Engineer 0",
        "company": "BKW Energie AG",
        "location": "Bern, Schweiz",
        "apply_url": f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[0]}/ats/",
        "description": "Build reliable energy platforms.",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id=f"bkw_switzerland-{JOB_IDS[0]}",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "BKW Switzerland import"
    assert stored["company"] == "BKW Energie AG"
