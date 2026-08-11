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
from app.services.parsers.companies.ntt_global_data_centers_switzerland import (
    ZURICH_LOCATION_FACET,
    NttGlobalDataCentersSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    requisition_id = f"JR{101121 + index}"
    return {
        "title": f"Litigation & Claims Counsel {index}",
        "externalPath": (
            f"/job/Hemel-Hempstead-UK/Litigation---Claims-Counsel-{index}_{requisition_id}"
        ),
        "locationsText": "6 Locations",
        "postedOn": "Posted 30+ Days Ago",
        "bulletFields": [requisition_id],
    }


def detail_payload(index: int, *, include_zurich: bool = True) -> dict[str, object]:
    requisition_id = f"JR{101121 + index}"
    additional_locations = ["Madrid, Spain", "Amsterdam, Netherlands"]
    if include_zurich:
        additional_locations.insert(0, "Zurich, Switzerland")
    return {
        "jobPostingInfo": {
            "title": f"Litigation & Claims Counsel {index}",
            "jobDescription": (
                "<h2>Your role</h2><p>Protect the company's interests.</p>"
                "<ul><li>Manage claims</li><li>Support disputes</li></ul>"
            ),
            "location": "Hemel Hempstead, UK",
            "additionalLocations": additional_locations,
            "startDate": "2026-07-01",
            "postedOn": "Posted 30+ Days Ago",
            "timeType": "Full time",
            "remoteType": "Remote",
            "jobReqId": requisition_id,
            "canApply": True,
            "posted": True,
            "externalUrl": (
                "https://nttglobaldatacenters.wd501.myworkdayjobs.com/External/job/"
                f"Hemel-Hempstead-UK/Litigation---Claims-Counsel-{index}_{requisition_id}"
            ),
            "country": {"descriptor": "United Kingdom", "id": "uk-id"},
        },
        "hiringOrganization": {"name": "NTT Global Data Centers EMEA UK Ltd."},
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int | None = None,
    include_facet: bool = True,
) -> dict[str, object]:
    catalog_total = len(records) if total is None else total
    payload: dict[str, object] = {
        "total": catalog_total,
        "jobPostings": records,
    }
    if include_facet:
        payload["facets"] = [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locations",
                        "descriptor": "Locations",
                        "values": [
                            {
                                "descriptor": "Zurich, Switzerland",
                                "id": ZURICH_LOCATION_FACET,
                                "count": catalog_total,
                            }
                        ],
                    }
                ],
            }
        ]
    return payload


def test_ntt_page_offsets_stop_on_page_containing_last_job() -> None:
    assert page_offsets(0) == []
    assert page_offsets(1) == [0]
    assert page_offsets(20) == [0]
    assert page_offsets(21) == [0, 20]
    assert page_offsets(45) == [0, 20, 40]


def test_ntt_collects_zurich_facet_and_enriches_multi_location_role() -> None:
    records = [listing_record(0)]
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appliedFacets"] == {"locations": [ZURICH_LOCATION_FACET]}
            assert body["limit"] == 20
            assert body["offset"] == 0
            return httpx.Response(200, json=listing_payload(records))
        return httpx.Response(200, json=detail_payload(0))

    parser = NttGlobalDataCentersSwitzerlandJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )
    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 2
    assert result.status == "completed"
    assert result.message == (
        "Scanned 1 verified NTT Global Data Centers vacancies for Zurich, Switzerland "
        "from 1 Workday facet records across 1 page requests"
    )
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "ntt_global_data_centers_switzerland"
    assert job.title == "Litigation & Claims Counsel 0"
    assert job.company == "NTT Global Data Centers EMEA UK Ltd."
    assert job.location == "Zurich, Switzerland"
    assert job.url and job.url.endswith("Claims-Counsel-0_JR101121")
    assert job.apply_url == job.url
    assert job.posted_at == "2026-07-01"
    assert job.employment_type == "Full time, Remote"
    assert job.description == (
        "Your role\nProtect the company's interests.\n- Manage claims\n- Support disputes"
    )
    assert job.raw["listing_offset"] == 0
    assert job.raw["total_available"] == 1


def test_ntt_removes_record_leaked_by_zurich_facet() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload([listing_record(0)]))
        return httpx.Response(200, json=detail_payload(0, include_zurich=False))

    result = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert "from 1 Workday facet records" in result.message


def test_ntt_preserves_verified_facet_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload([listing_record(0)]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        NttGlobalDataCentersSwitzerlandJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Litigation & Claims Counsel 0"
    assert job.company == "NTT Global Data Centers"
    assert job.location == "Zurich, Switzerland"
    assert job.url and job.url.endswith("Claims-Counsel-0_JR101121")
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ntt_rejects_invalid_payload_path_or_facet() -> None:
    invalid = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"total": 1, "jobPostings": {}})
        )
    )
    unsafe_record = listing_record(0)
    unsafe_record["externalPath"] = "https://evil.example/job/Engineer_JR101121"
    unsafe = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_payload([unsafe_record]))
        )
    )
    missing_facet = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([listing_record(0)], include_facet=False),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="unsafe vacancy path"):
        unsafe.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="verified Zurich facet"):
        missing_facet.search(LinkedInSearchRequest())


def test_ntt_rejects_truncated_or_oversized_catalog() -> None:
    truncated = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([listing_record(0)], total=2),
            )
        )
    )
    oversized = NttGlobalDataCentersSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(20)],
                    total=21,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_ntt_wraps_listing_request_failures() -> None:
    parser = NttGlobalDataCentersSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_ntt_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ntt_global_data_centers_switzerland"]
    assert isinstance(parser, NttGlobalDataCentersSwitzerlandJobsParser)
    assert parser.base_url == settings.ntt_global_data_centers_switzerland_jobs_base_url
    assert parser.max_pages == settings.ntt_global_data_centers_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.ntt_global_data_centers_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "NTT Global Data Centers", "filters": {}},
            "sources": [
                "ntt_global_data_centers_switzerland",
                "ntt_global_data_centers_switzerland",
            ],
        }
    )
    assert request.sources == ["ntt_global_data_centers_switzerland"]


def test_ntt_jobs_render_as_direct_company_imports() -> None:
    parser = NttGlobalDataCentersSwitzerlandJobsParser()
    record = listing_record(0)
    record["detail"] = detail_payload(0)
    job = parser.normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="ntt_global_data_centers_switzerland-jr101121",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "NTT Global Data Centers import"
    assert stored["id"] == "ntt_global_data_centers_switzerland-jr101121"
