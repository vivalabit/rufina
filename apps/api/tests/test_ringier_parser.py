from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.ringier import RingierJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, Any]:
    viewkey = f"00000000-0000-4000-8000-{index:012d}"
    return {
        "id": str(10_100_000 + index),
        "hk_id": str(1_000_000 + index),
        "viewkey": viewkey,
        "title": f"System Engineer {index} (a)*",
        "attributes": {
            "90": ["Permanent contract", "Full time"],
            "80": ["80 - 100%"],
            "60": ["IT / Data Management"],
            "50": ["Zofingen", "Zürich"],
            "30": ["Employee"],
            "20": ["Ringier AG"],
            "10": ["Swiss midland"],
        },
        "szas": {
            "sza_location.country": "Schweiz",
            "sza_title": f"System Engineer {index} (a)*",
            "sza_short_description": "Build Ringier's digital workplace.",
            "sza_introduction": ("<p>Build Ringier&#39;s reliable digital workplace.</p>"),
            "sza_tasks": ("<ul><li>Operate identity services</li><li>Automate access</li></ul>"),
            "sza_requirements": "<ul><li>Okta &amp; API experience</li></ul>",
            "sza_pensum": "80-100%",
            "sza_role": "Mitarbeiter/in",
        },
        "links": {
            "directlink": (
                f"https://jobs.ringier.ch/offene-stellen/system-engineer-{index}/{viewkey}"
            )
        },
        "start_date": "2026-08-07T05:39:32Z",
        "last_modification_timestamp": "2026-08-07T13:23:59Z",
        "language": "de",
    }


def catalog_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(records),
        "filtercount": None,
        "offset": 0,
        "medium_id": "2021",
        "medium_name": None,
        "jobs": records,
    }


def test_ringier_scans_and_normalizes_full_swiss_catalog() -> None:
    requested: list[httpx.Request] = []
    records = [listing_record(1), listing_record(2)]
    records[1]["attributes"]["30"] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json=catalog_payload(records))

    parser = RingierJobsParser(
        base_url="https://career.ringier.test/en/career",
        api_url="https://career.ringier.test/api/jobs-ringier-en.json",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(requested) == 1
    assert requested[0].url.path == "/api/jobs-ringier-en.json"
    assert requested[0].headers["origin"] == "https://career.ringier.test"
    assert requested[0].headers["referer"] == parser.base_url
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Swiss Ringier vacancies from the full Prospective catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "ringier"
    assert first.title == "System Engineer 1 (a)*"
    assert first.company == "Ringier AG"
    assert first.location == "Zofingen, Zürich"
    assert first.url == (
        "https://jobs.ringier.ch/offene-stellen/system-engineer-1/"
        "00000000-0000-4000-8000-000000000001"
    )
    assert first.apply_url == (
        "https://ohws.prospective.ch/public/v1/redirect/00000000-0000-4000-8000-000000000001/ats/"
    )
    assert first.posted_at == "2026-08-07T05:39:32Z"
    assert first.employment_type == "Permanent contract, Full time, 80-100%"
    assert first.seniority == "Employee"
    assert first.description == (
        "Introduction\nBuild Ringier's reliable digital workplace.\n\n"
        "Responsibilities\n- Operate identity services\n- Automate access\n\n"
        "Requirements\n- Okta & API experience"
    )
    assert first.raw["id"] == "10100001"
    assert first.raw["szas"]["sza_location.country"] == "Schweiz"
    assert result.jobs[1].seniority is None


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "full-catalog contract"),
        (
            {
                "total": 1,
                "offset": 0,
                "medium_id": "2021",
                "jobs": [],
            },
            "declared 1",
        ),
        (
            {
                "total": 0,
                "offset": 96,
                "medium_id": "2021",
                "jobs": [],
            },
            "full-catalog contract",
        ),
    ],
)
def test_ringier_rejects_invalid_full_catalog_contract(
    payload: object,
    message: str,
) -> None:
    parser = RingierJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_ringier_rejects_non_swiss_vacancy() -> None:
    record = listing_record(1)
    record["szas"]["sza_location.country"] = "Deutschland"
    parser = RingierJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=catalog_payload([record])))
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_ringier_rejects_duplicate_identifiers() -> None:
    duplicate = listing_record(2)
    duplicate["id"] = listing_record(1)["id"]
    parser = RingierJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=catalog_payload([listing_record(1), duplicate]),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy"):
        parser.search(LinkedInSearchRequest())


def test_ringier_enforces_catalog_size_limit() -> None:
    parser = RingierJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=catalog_payload([listing_record(1), listing_record(2)]),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_ringier_wraps_catalog_request_failures() -> None:
    parser = RingierJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_ringier_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ringier"]
    assert isinstance(parser, RingierJobsParser)
    assert parser.base_url == settings.ringier_jobs_base_url
    assert parser.api_url == settings.ringier_jobs_api_url
    assert parser.max_jobs == settings.ringier_jobs_max_jobs
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Ringier", "filters": {}},
            "sources": ["ringier", "ringier"],
        }
    )
    assert request.sources == ["ringier"]


def test_ringier_jobs_render_as_direct_company_imports() -> None:
    job = RingierJobsParser().normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="ringier-10100001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Ringier import"
    assert stored["id"] == "ringier-10100001"


def test_ringier_uses_workload_when_contract_facet_is_empty() -> None:
    record = listing_record(1)
    record["attributes"]["90"] = []
    record["szas"]["sza_pensum"] = "Temps complet"
    result = RingierJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=catalog_payload([record]))
        )
    ).search(LinkedInSearchRequest())
    assert len(result.jobs) == 1
    assert result.jobs[0].employment_type == "Temps complet"
