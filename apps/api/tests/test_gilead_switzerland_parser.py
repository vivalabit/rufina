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
from app.services.parsers.companies.gilead_switzerland import (
    EXPECTED_COMPANY,
    GILEAD_SWITZERLAND_LOCATION,
    GILEAD_SWITZERLAND_LOCATION_NAME,
    SWITZERLAND_COUNTRY_ID,
    GileadSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Virology Coordinator {index}",
        "externalPath": (
            f"/job/Switzerland---Zug/Virology-Coordinator-{index}_R{index:07d}-1"
        ),
        "locationsText": "Switzerland - Zug",
        "postedOn": "Posted 3 Days Ago",
        "bulletFields": [f"R{index:07d}"],
    }


def detail_payload(
    index: int,
    *,
    organization: str = "2140 Gilead Sciences Switzerland Sarl",
    country: str = "Switzerland",
    country_id: str = SWITZERLAND_COUNTRY_ID,
) -> dict[str, object]:
    path = listing_record(index)["externalPath"]
    return {
        "jobPostingInfo": {
            "title": f"Administrative Coordinator Virology {index}",
            "jobDescription": (
                "<h2>Role purpose</h2><p>Support the Swiss Virology team.</p>"
                "<ul><li>Coordinate meetings</li><li>Manage suppliers</li></ul>"
            ),
            "location": "Switzerland - Zug",
            "startDate": "2026-07-27",
            "timeType": "Full time",
            "remoteType": "Onsite Required",
            "jobReqId": f"R{index:07d}",
            "country": {"descriptor": country, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "CH - Zug",
                "country": {
                    "descriptor": country,
                    "id": country_id,
                    "alpha2Code": "CH" if country == "Switzerland" else "DE",
                },
            },
            "externalUrl": (
                f"https://gilead.example.test/gileadcareers{path}"
            ),
        },
        "hiringOrganization": {"name": organization},
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int | None = None,
    include_facets: bool = True,
) -> dict[str, object]:
    declared_total = len(records) if total is None else total
    payload: dict[str, object] = {
        "total": declared_total,
        "jobPostings": records,
    }
    if include_facets:
        payload["facets"] = [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locations",
                        "descriptor": "Locations",
                        "values": [
                            {
                                "descriptor": GILEAD_SWITZERLAND_LOCATION_NAME,
                                "id": GILEAD_SWITZERLAND_LOCATION,
                                "count": declared_total,
                            }
                        ],
                    }
                ],
            }
        ]
    return payload


@pytest.mark.parametrize(
    ("total", "expected"),
    [(0, []), (1, [0]), (20, [0]), (21, [0, 20]), (41, [0, 20, 40])],
)
def test_page_offsets(total: int, expected: list[int]) -> None:
    assert page_offsets(total) == expected


def test_gilead_fetches_full_location_facet_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(21)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appliedFacets"] == {
                "locations": [GILEAD_SWITZERLAND_LOCATION]
            }
            assert body["limit"] == 20
            offset = body["offset"]
            listing_offsets.append(offset)
            return httpx.Response(
                200,
                json=listing_payload(
                    records[offset : offset + 20],
                    total=len(records) if offset == 0 else 0,
                    include_facets=offset == 0,
                ),
                request=request,
            )
        detail_requests.append(request.url.path)
        index = int(request.url.path.split("Virology-Coordinator-")[1].split("_")[0])
        return httpx.Response(200, json=detail_payload(index), request=request)

    result = GileadSwitzerlandJobsParser(
        base_url=(
            "https://gilead.example.test/gileadcareers?"
            f"locations={GILEAD_SWITZERLAND_LOCATION}"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20]
    assert len(detail_requests) == 21
    assert result.message == (
        "Scanned 21 verified Gilead Switzerland vacancies from 21 Workday "
        "location records across 2 page requests in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 21
    first = result.jobs[0]
    assert first.source == "gilead_switzerland"
    assert first.title == "Administrative Coordinator Virology 0"
    assert first.company == EXPECTED_COMPANY
    assert first.location == "Switzerland - Zug"
    assert first.url.endswith("/Virology-Coordinator-0_R0000000-1")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-07-27"
    assert first.employment_type == "Full time, Onsite Required"
    assert first.description == (
        "Role purpose\nSupport the Swiss Virology team.\n"
        "- Coordinate meetings\n- Manage suppliers"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 21


def test_gilead_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_payload([listing_record(7)]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = GileadSwitzerlandJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Virology Coordinator 7"
    assert job.company == EXPECTED_COMPANY
    assert job.location == "Switzerland - Zug"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_gilead_rejects_unverified_location_facet() -> None:
    payload = listing_payload([listing_record(1)])
    payload["facets"][0]["values"][0]["values"][0]["descriptor"] = "Germany"  # type: ignore[index]
    parser = GileadSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="verified location facet"):
        parser.search(LinkedInSearchRequest())


def test_gilead_removes_foreign_or_unverified_details() -> None:
    records = [listing_record(1), listing_record(2)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload(records), request=request)
        index = int(request.url.path.split("Virology-Coordinator-")[1].split("_")[0])
        if index == 2:
            return httpx.Response(
                200,
                json=detail_payload(
                    2,
                    organization="Gilead Sciences GmbH",
                    country="Germany",
                    country_id="germany-id",
                ),
                request=request,
            )
        return httpx.Response(200, json=detail_payload(1), request=request)

    result = GileadSwitzerlandJobsParser(
        base_url="https://gilead.example.test/gileadcareers",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == [
        "Administrative Coordinator Virology 1"
    ]
    assert "from 2 Workday location records" in result.message


def test_gilead_rejects_malformed_truncated_and_oversized_catalogs() -> None:
    malformed = GileadSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"total": 1, "jobPostings": {}},
                request=request,
            )
        )
    )
    truncated = GileadSwitzerlandJobsParser(
        max_catalog_passes=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload([listing_record(1)], total=2),
                request=request,
            )
        ),
    )
    oversized = GileadSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(20)],
                    total=21,
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobPostings"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_gilead_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["gilead_switzerland"]

    assert isinstance(parser, GileadSwitzerlandJobsParser)
    assert parser.base_url == settings.gilead_switzerland_jobs_base_url
    assert parser.max_pages == settings.gilead_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.gilead_switzerland_jobs_max_catalog_passes
    )
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Gilead Sciences Switzerland", "filters": {}},
            "sources": ["gilead_switzerland", "gilead_switzerland"],
        }
    )
    assert request.sources == ["gilead_switzerland"]

    record = listing_record(1)
    record["detail"] = detail_payload(1)
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="gilead_switzerland-r0053823",
        added_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == f"{EXPECTED_COMPANY} import"
    assert stored["company"] == EXPECTED_COMPANY
