from __future__ import annotations

import json
from datetime import UTC, datetime
from math import ceil

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.equans_switzerland import (
    EQUANS_FILTERS,
    EQUANS_RESULTS_PER_PAGE,
    EquansSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = (
    "https://www.equans.test/join-us?jobs_offer%5BrefinementList%5D"
    "%5Bcountry_en%5D%5B0%5D=Switzerland"
)
SEARCH_URL = "https://equans.test/1/indexes/jobs_offer/query"


def catalog_record(index: int) -> dict[str, object]:
    job_id = str(100001000 + index)
    return {
        "objectID": job_id,
        "id": int(job_id),
        "title_en": f"Technische:r Hauswart:in {index}",
        "description_en": f"Maintain Swiss buildings and systems {index}.",
        "country_en": "Switzerland",
        "region_en": {
            "name": "CH-ZH",
            "label": "Switzerland - CH-ZH",
            "hierarchicalTerm.lvl0": "Switzerland",
            "hierarchicalTerm.lvl1": "Switzerland > CH-ZH",
        },
        "locality_en": "Zürich",
        "state_en": "CH-ZH",
        "address_en": "Hohlstrasse 100",
        "zip_code_en": "8004",
        "contract_type_en": "CHE_Permanent",
        "job_scheddule_en": "Full time",
        "url_en": f"/en/jobs/{job_id}-technischer-hauswart-{index}",
        "apply_url_en": "https://careers.equans.com/apply/job-offer",
        "type": "success_factor",
        "created_at": "2026-08-12 13:25:07",
        "updated_at": "2026-08-13 09:10:11",
    }


def search_payload(
    records: list[dict[str, object]],
    *,
    total: int,
    page: int,
) -> dict[str, object]:
    return {
        "hits": records,
        "page": page,
        "nbHits": total,
        "nbPages": ceil(total / EQUANS_RESULTS_PER_PAGE) if total else 0,
        "hitsPerPage": EQUANS_RESULTS_PER_PAGE,
        "exhaustiveNbHits": True,
        "facets": {"country_en": {"Switzerland": total}},
    }


def request_page(request: httpx.Request) -> int:
    assert request.method == "POST"
    assert request.url == httpx.URL(SEARCH_URL)
    assert request.headers["x-algolia-application-id"] == "test-app"
    assert request.headers["x-algolia-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["query"] == ""
    assert body["filters"] == EQUANS_FILTERS
    assert body["hitsPerPage"] == EQUANS_RESULTS_PER_PAGE
    assert body["facets"] == ["country_en"]
    assert "description_en" in body["attributesToRetrieve"]
    return int(body["page"])


def test_equans_scans_complete_swiss_catalog() -> None:
    records = [catalog_record(index) for index in range(26)]
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request_page(request)
        requested_pages.append(page)
        start = page * EQUANS_RESULTS_PER_PAGE
        return httpx.Response(
            200,
            json=search_payload(
                records[start : start + EQUANS_RESULTS_PER_PAGE],
                total=len(records),
                page=page,
            ),
            request=request,
        )

    result = EquansSwitzerlandJobsParser(
        base_url=BASE_URL,
        search_url=SEARCH_URL,
        application_id="test-app",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requested_pages == [0, 1]
    assert len(result.jobs) == 26
    assert result.message == (
        "Scanned 26 Equans Switzerland vacancies from 26 Swiss catalog records "
        "across 2 API page requests"
    )
    job = result.jobs[0]
    assert job.source == "equans_switzerland"
    assert job.title == "Technische:r Hauswart:in 0"
    assert job.company == "Equans"
    assert job.location == "Zürich, CH-ZH, Switzerland"
    assert job.url == ("https://www.equans.test/en/jobs/100001000-technischer-hauswart-0")
    assert job.apply_url == job.url
    assert job.posted_at == "2026-08-12 13:25:07"
    assert job.employment_type == "Permanent · Full time"
    assert job.seniority is None
    assert job.description == "Maintain Swiss buildings and systems 0."
    assert job.raw["apply_url_en"] == ("https://careers.equans.com/apply/job-offer")
    assert job.raw["listing_page"] == 0
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 26


def test_equans_retries_a_shifted_catalog_until_ids_are_stable() -> None:
    records = [catalog_record(index) for index in range(26)]
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request_page(request)
        requested_pages.append(page)
        if page == 0:
            page_records = records[:24]
        elif requested_pages.count(1) == 1:
            page_records = [records[23], records[25]]
        else:
            page_records = records[24:]
        return httpx.Response(
            200,
            json=search_payload(page_records, total=26, page=page),
            request=request,
        )

    result = EquansSwitzerlandJobsParser(
        search_url=SEARCH_URL,
        application_id="test-app",
        api_key="test-key",
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert requested_pages == [0, 1, 0, 1]
    assert len(result.jobs) == 26
    assert result.message.endswith("across 4 API page requests")


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({**catalog_record(0), "country_en": "Germany"}, "non-Swiss vacancy"),
        (
            {
                **catalog_record(0),
                "url_en": "/en/jobs/100009999-another-vacancy",
            },
            "non-Swiss vacancy",
        ),
    ],
)
def test_equans_rejects_invalid_or_non_swiss_records(
    record: dict[str, object],
    message: str,
) -> None:
    parser = EquansSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=search_payload([record], total=1, page=0),
                request=request,
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_equans_rejects_inconsistent_swiss_facets() -> None:
    payload = search_payload([catalog_record(0)], total=1, page=0)
    payload["facets"] = {"country_en": {"Switzerland": 2}}
    parser = EquansSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="Swiss facets"):
        parser.search(LinkedInSearchRequest())


def test_equans_enforces_page_limit() -> None:
    parser = EquansSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=search_payload(
                    [catalog_record(index) for index in range(24)],
                    total=25,
                    page=0,
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_equans_wraps_search_request_failures() -> None:
    parser = EquansSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_equans_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["equans_switzerland"]
    assert isinstance(parser, EquansSwitzerlandJobsParser)
    assert parser.base_url == settings.equans_switzerland_jobs_base_url
    assert parser.search_url == settings.equans_switzerland_jobs_search_url
    assert parser.application_id == settings.equans_switzerland_jobs_application_id
    assert parser.api_key == settings.equans_switzerland_jobs_api_key
    assert parser.max_pages == settings.equans_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.equans_switzerland_jobs_max_catalog_passes

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Equans", "filters": {}},
            "sources": ["equans_switzerland", "equans_switzerland"],
        }
    )
    assert request.sources == ["equans_switzerland"]


def test_equans_jobs_render_as_direct_company_imports() -> None:
    parsed = EquansSwitzerlandJobsParser().normalize_job(catalog_record(0))
    stored = parsed_job_to_stored_job(
        parsed,
        job_id="equans_switzerland-100001000",
        added_at=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
    )

    assert stored["id"] == "equans_switzerland-100001000"
    assert stored["logo"] == "company"
    assert stored["department"] == "Equans Switzerland import"
    assert stored["company"] == "Equans"
