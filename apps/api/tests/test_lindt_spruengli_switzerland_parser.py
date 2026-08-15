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
from app.services.parsers.companies.lindt_spruengli_switzerland import (
    EXPECTED_COMPANY,
    LINDT_SPRUENGLI_SWITZERLAND_HIRING_COMPANY,
    SWITZERLAND_COUNTRY_FACET,
    LindtSpruengliSwitzerlandJobsParser,
    normalize_job,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "title": f"Chocolate Engineer {index}",
        "externalPath": (f"/job/Kilchberg-Switzerland/Chocolate-Engineer-{index}_JR{index:05d}"),
        "locationsText": "Kilchberg, Switzerland",
        "postedOn": "Posted 3 Days Ago",
        "bulletFields": [f"JR{index:05d}"],
    }


def detail_payload(
    index: int,
    *,
    company: str = EXPECTED_COMPANY,
    country: str = "Switzerland",
    country_id: str = SWITZERLAND_COUNTRY_FACET,
) -> dict[str, object]:
    path = listing_record(index)["externalPath"]
    return {
        "jobPostingInfo": {
            "title": f"Senior Chocolate Engineer {index}",
            "jobDescription": (
                "<h2>Deine Aufgaben</h2><p>Entwickle feinste Schokolade.</p>"
                "<ul><li>Leite Projekte</li><li>Verbessere Prozesse</li></ul>"
            ),
            "location": "Kilchberg, Switzerland",
            "startDate": "2026-08-14",
            "timeType": "Full time",
            "remoteType": "Hybrid",
            "jobReqId": f"JR{index:05d}",
            "country": {"descriptor": country, "id": country_id},
            "jobRequisitionLocation": {
                "descriptor": "Kilchberg",
                "country": {
                    "descriptor": country,
                    "id": country_id,
                    "alpha2Code": "CH" if country == "Switzerland" else "DE",
                },
            },
            "externalUrl": (
                f"https://lindtspruengli.example.test/LindtSpruengliGroupCareers{path}"
            ),
        },
        "hiringOrganization": {"name": company},
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
                "facetParameter": "hiringCompany",
                "descriptor": "Company",
                "values": [
                    {
                        "descriptor": EXPECTED_COMPANY,
                        "id": LINDT_SPRUENGLI_SWITZERLAND_HIRING_COMPANY,
                        "count": declared_total,
                    }
                ],
            }
        ]
    return payload


@pytest.mark.parametrize(
    ("total", "expected"),
    [(0, []), (1, [0]), (20, [0]), (21, [0, 20]), (44, [0, 20, 40])],
)
def test_page_offsets(total: int, expected: list[int]) -> None:
    assert page_offsets(total) == expected


def test_lindt_fetches_full_hiring_company_facet_and_enriches_details() -> None:
    records = [listing_record(index) for index in range(21)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appliedFacets"] == {
                "hiringCompany": [LINDT_SPRUENGLI_SWITZERLAND_HIRING_COMPANY]
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
        index = int(request.url.path.split("Chocolate-Engineer-")[1].split("_")[0])
        return httpx.Response(200, json=detail_payload(index), request=request)

    result = LindtSpruengliSwitzerlandJobsParser(
        base_url=(
            "https://lindtspruengli.example.test/LindtSpruengliGroupCareers?"
            f"hiringCompany={LINDT_SPRUENGLI_SWITZERLAND_HIRING_COMPANY}"
        ),
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == [0, 20]
    assert len(detail_requests) == 21
    assert result.message == (
        "Scanned 21 verified Lindt & Sprüngli Switzerland vacancies from 21 "
        "Workday facet records across 2 page requests in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 21
    first = result.jobs[0]
    assert first.source == "lindt_spruengli_switzerland"
    assert first.title == "Senior Chocolate Engineer 0"
    assert first.company == EXPECTED_COMPANY
    assert first.location == "Kilchberg, Switzerland"
    assert first.url.endswith("/Chocolate-Engineer-0_JR00000")
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-14"
    assert first.employment_type == "Full time, Hybrid"
    assert first.description == (
        "Deine Aufgaben\nEntwickle feinste Schokolade.\n- Leite Projekte\n- Verbessere Prozesse"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["total_available"] == 21


def test_lindt_rejects_unverified_hiring_company_facet() -> None:
    payload = listing_payload([listing_record(1)])
    payload["facets"][0]["values"][0]["descriptor"] = "Another company"  # type: ignore[index]

    parser = LindtSpruengliSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="verified hiring-company facet"):
        parser.search(LinkedInSearchRequest())


def test_lindt_removes_foreign_detail_leaked_by_facet() -> None:
    records = [listing_record(1), listing_record(2)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=listing_payload(records), request=request)
        index = int(request.url.path.split("Chocolate-Engineer-")[1].split("_")[0])
        if index == 2:
            return httpx.Response(
                200,
                json=detail_payload(
                    2,
                    company="Chocoladefabriken Lindt & Sprüngli GmbH",
                    country="Germany",
                    country_id="germany-id",
                ),
                request=request,
            )
        return httpx.Response(200, json=detail_payload(1), request=request)

    result = LindtSpruengliSwitzerlandJobsParser(
        base_url="https://lindtspruengli.example.test/LindtSpruengliGroupCareers",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert [job.title for job in result.jobs] == ["Senior Chocolate Engineer 1"]
    assert "from 2 Workday facet records" in result.message


def test_lindt_preserves_verified_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_payload([listing_record(7)]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        LindtSpruengliSwitzerlandJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.title == "Chocolate Engineer 7"
    assert job.company == EXPECTED_COMPANY
    assert job.location == "Kilchberg, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_lindt_rejects_truncated_or_oversized_catalog() -> None:
    truncated = LindtSpruengliSwitzerlandJobsParser(
        max_catalog_passes=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload([listing_record(1)], total=2),
                request=request,
            )
        ),
    )
    oversized = LindtSpruengliSwitzerlandJobsParser(
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

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_lindt_wraps_workday_request_failure() -> None:
    parser = LindtSpruengliSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="Workday request failed"):
        parser.search(LinkedInSearchRequest())


def test_lindt_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["lindt_spruengli_switzerland"]

    assert isinstance(parser, LindtSpruengliSwitzerlandJobsParser)
    assert parser.base_url == settings.lindt_spruengli_switzerland_jobs_base_url
    assert parser.max_pages == settings.lindt_spruengli_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.lindt_spruengli_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Lindt & Sprüngli Switzerland", "filters": {}},
            "sources": ["lindt_spruengli_switzerland", "lindt_spruengli_switzerland"],
        }
    )
    assert request.sources == ["lindt_spruengli_switzerland"]

    record = listing_record(1)
    record["detail"] = detail_payload(1)
    stored = parsed_job_to_stored_job(
        normalize_job(record, parser=parser),
        job_id="lindt_spruengli_switzerland-jr00001",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == f"{EXPECTED_COMPANY} import"
    assert stored["company"] == EXPECTED_COMPANY
