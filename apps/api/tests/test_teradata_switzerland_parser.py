from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.teradata_switzerland import (
    TERADATA_LOCATION,
    TERADATA_PAGE_SIZE,
    TeradataSwitzerlandJobsParser,
    page_offsets,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(index: int, *, swiss: bool = True) -> dict[str, object]:
    key = str(220353 + index)
    title = f"Customer Solution Architect {index}"
    locations = ["London, UK"]
    if swiss:
        locations.append("Zurich, Switzerland")
    posted_at = "2026-07-07T06:18:08.710Z"
    return {
        "__typename": "JobPosting",
        "id": base64.b64encode(f"JobPosting/{key}".encode()).decode(),
        "key": key,
        "number": key,
        "status": "OPEN",
        "title": title,
        "descriptionHTML": (
            "<h2>What you'll do</h2><p>Design trusted data solutions.</p>"
            "<ul><li>Guide customers</li><li>Build architectures</li></ul>"
        ),
        "workplaceType": "REMOTE",
        "postType": "INT_EXT",
        "structuredDataJSON": json.dumps(
            {
                "@context": "http://schema.org/",
                "@type": "JobPosting",
                "title": title,
                "identifier": key,
                "datePosted": posted_at,
                "hiringOrganization": {
                    "@type": "Organization",
                    "name": "Teradata",
                },
            }
        ),
        "positionType": {
            "__typename": "PositionType",
            "id": "UG9zaXRpb25UeXBlLzI=",
            "name": "Full Time",
        },
        "primaryPlace": {"name": "London, UK"},
        "places": {
            "__typename": "PlaceConnection",
            "nodes": [
                {
                    "__typename": "Place",
                    "name": location,
                    "id": base64.b64encode(f"Place/{location}".encode()).decode(),
                }
                for location in locations
            ],
            "pageInfo": {
                "__typename": "PageInfo",
                "hasNextPage": False,
                "hasPreviousPage": False,
            },
        },
        "postedOn": posted_at,
    }


def api_payload(
    records: list[dict[str, object]],
    *,
    total: int | None = None,
    offset: int = 0,
) -> dict[str, object]:
    catalog_total = len(records) if total is None else total
    return {
        "data": {
            "searchJobs": {
                "__typename": "JobPostingSearch",
                "results": {
                    "__typename": "JobPostingConnection",
                    "nodes": records,
                    "pageInfo": {
                        "hasNextPage": offset + len(records) < catalog_total,
                        "hasPreviousPage": offset > 0,
                        "startCursor": None,
                        "endCursor": None,
                    },
                    "totalCount": catalog_total,
                },
            }
        }
    }


def test_teradata_page_offsets_include_empty_catalog_request() -> None:
    assert page_offsets(0) == [0]
    assert page_offsets(1) == [0]
    assert page_offsets(TERADATA_PAGE_SIZE) == [0]
    assert page_offsets(TERADATA_PAGE_SIZE + 1) == [0, TERADATA_PAGE_SIZE]


def test_teradata_collects_and_normalizes_multi_location_swiss_role() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=api_payload([vacancy(0)]))

    result = TeradataSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert requests == [
        {
            "operationName": "searchJobs",
            "variables": {
                "query": None,
                "first": TERADATA_PAGE_SIZE,
                "start": 0,
                "filters": {"location": [{"address": TERADATA_LOCATION}]},
            },
            "extensions": {"trustedDocument": {"id": "search-jobs"}},
        }
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 1 Teradata Switzerland vacancies from 1 GR8 People records across 1 page requests"
    )
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "teradata_switzerland"
    assert job.title == "Customer Solution Architect 0"
    assert job.company == "Teradata"
    assert job.location == "Zurich, Switzerland"
    assert job.url == ("https://careers.teradata.com/jobs/220353/customer-solution-architect-0")
    assert job.apply_url == (
        "https://careers.teradata.com/login?dest=%2Fjobs%2F220353%2F"
        "customer-solution-architect-0%2Fapply"
    )
    assert job.posted_at == "2026-07-07"
    assert job.employment_type == "Full Time, Remote"
    assert job.description == (
        "What you'll do\nDesign trusted data solutions.\n- Guide customers\n- Build architectures"
    )
    assert job.raw["listing_offset"] == 0


def test_teradata_empty_swiss_catalog_is_a_complete_result() -> None:
    parser = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=api_payload([])))
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Teradata Switzerland vacancies from 0 GR8 People records across 1 page requests"
    )


def test_teradata_paginates_all_filtered_records() -> None:
    records = [vacancy(index) for index in range(TERADATA_PAGE_SIZE + 1)]
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = json.loads(request.content)["variables"]["start"]
        offsets.append(offset)
        page = records[offset : offset + TERADATA_PAGE_SIZE]
        return httpx.Response(
            200,
            json=api_payload(page, total=len(records), offset=offset),
        )

    result = TeradataSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert offsets == [0, TERADATA_PAGE_SIZE]
    assert len(result.jobs) == TERADATA_PAGE_SIZE + 1


def test_teradata_rejects_non_swiss_or_mismatched_records() -> None:
    non_swiss = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=api_payload([vacancy(0, swiss=False)]))
        )
    )
    mismatched = vacancy(0)
    mismatched["number"] = "999999"
    invalid_record = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=api_payload([mismatched])))
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        non_swiss.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete Swiss vacancy"):
        invalid_record.search(LinkedInSearchRequest())


def test_teradata_rejects_graphql_errors_truncated_or_oversized_catalogs() -> None:
    graphql_error = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"errors": [{"message": "failed"}]})
        )
    )
    truncated = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=api_payload([vacancy(0)], total=2))
        )
    )
    oversized = TeradataSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=api_payload(
                    [vacancy(index) for index in range(TERADATA_PAGE_SIZE)],
                    total=TERADATA_PAGE_SIZE + 1,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="contains errors"):
        graphql_error.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete page"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_teradata_wraps_request_failures() -> None:
    parser = TeradataSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_teradata_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["teradata_switzerland"]
    assert isinstance(parser, TeradataSwitzerlandJobsParser)
    assert parser.base_url == settings.teradata_switzerland_jobs_base_url
    assert parser.api_url == settings.teradata_switzerland_jobs_api_url
    assert parser.max_pages == settings.teradata_switzerland_jobs_max_pages

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Teradata Switzerland", "filters": {}},
            "sources": ["teradata_switzerland", "teradata_switzerland"],
        }
    )
    assert request.sources == ["teradata_switzerland"]


def test_teradata_jobs_render_as_direct_company_imports() -> None:
    parser = TeradataSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy_record())
    stored = parsed_job_to_stored_job(
        job,
        job_id="teradata_switzerland-220353",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Teradata Switzerland import"
    assert stored["id"] == "teradata_switzerland-220353"


def vacancy_record() -> dict[str, object]:
    raw = vacancy(0)
    return {
        **raw,
        "key": "220353",
        "title": "Customer Solution Architect 0",
        "location": "Zurich, Switzerland",
        "posted_at": "2026-07-07",
        "position_type": "Full Time",
        "workplace_type": "Remote",
        "description": "Design trusted data solutions.",
        "listing_offset": 0,
    }
