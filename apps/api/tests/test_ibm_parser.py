from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.ibm import IbmJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    job_id = str(125_000 + index)
    return {
        "title": f"Cloud Engineer {index}",
        "description": "Build cloud platforms.",
        "url": (
            "https://careers.ibm.test/de_DE/careers/JobDetail?"
            f"jobId={job_id}&source=WEB_Search_EMEA"
        ),
        "docattributes": [
            {"country": "ch"},
            {"dcdate": "2026-08-07"},
            {"effectivedate": "2026-08-08"},
            {"expiredate": "2026-09-08"},
            {"field_keyword_05": "Switzerland"},
            {"field_keyword_08": "Cloud"},
            {"field_keyword_17": "Hybrid"},
            {"field_keyword_18": "Professional"},
            {"field_keyword_19": "Zurich, CH"},
            {"field_keyword_20": "IBM Schweiz AG"},
            {"field_text_01": job_id},
            {
                "raw_body": (
                    "<p>Shape IBM cloud platforms.</p>"
                    "<ul><li>Build services</li><li>Support clients</li></ul>"
                )
            },
        ],
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int,
    start_index: int,
) -> dict[str, object]:
    return {
        "resultset": {
            "searchresults": {
                "totalresults": total,
                "startindex": start_index,
                "numresults": len(records),
                "searchresultlist": records,
            }
        }
    }


def test_ibm_fetches_complete_catalog_and_normalizes_records() -> None:
    records = [listing_record(index) for index in range(31)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/responseFormat/json")
        assert request.url.params["scope"] == "careers2"
        assert request.url.params["rmdt"] == "ALL"
        assert request.url.params["appid"] == "careers"
        assert request.url.params["nr"] == "30"
        assert request.url.params["query"] == ""
        assert request.url.params["filter"] == "field_keyword_05:Switzerland"
        offset = int(request.url.params["fr"])
        assert int(request.url.params["page"]) == (offset // 30) + 1
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=listing_payload(
                records[offset : offset + 30],
                total=len(records),
                start_index=offset,
            ),
        )

    parser = IbmJobsParser(
        base_url="https://www.ibm.test/careers/search",
        api_url="https://www-api.ibm.test/search/responseFormat/json",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 30]
    assert result.status == "completed"
    assert result.search_url == "https://www.ibm.test/careers/search"
    assert result.message == (
        "Scanned 31 IBM Switzerland vacancies from 31 catalog records across 2 API page requests"
    )
    assert len(result.jobs) == 31
    first = result.jobs[0]
    assert first.source == "ibm"
    assert first.title == "Cloud Engineer 0"
    assert first.company == "IBM"
    assert first.location == "Zurich, CH"
    assert first.url == (
        "https://careers.ibm.com/de_DE/careers/JobDetail?jobId=125000&source=WEB_Search_EMEA"
    )
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-08"
    assert first.employment_type == "Hybrid"
    assert first.seniority == "Professional"
    assert first.description == ("Shape IBM cloud platforms.\n- Build services\n- Support clients")
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 31


def test_ibm_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(31)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["fr"])
        requested_offsets.append(offset)
        if offset == 0:
            page_records = records[:30]
        elif requested_offsets.count(30) == 1:
            page_records = [records[29]]
        else:
            page_records = records[30:]
        return httpx.Response(
            200,
            json=listing_payload(
                page_records,
                total=len(records),
                start_index=offset,
            ),
        )

    parser = IbmJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 30, 0, 30]
    assert len(result.jobs) == 31
    assert result.message.endswith("across 4 API page requests")


def test_ibm_rejects_invalid_or_non_swiss_payload() -> None:
    invalid = IbmJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"resultset": {}}))
    )
    non_swiss_record = listing_record(1)
    non_swiss_record["docattributes"] = [
        {"country": "de"},
        {"field_keyword_05": "Germany"},
        {"field_text_01": "125001"},
    ]
    non_swiss = IbmJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([non_swiss_record], total=1, start_index=0),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid search results"):
        invalid.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        non_swiss.search(LinkedInSearchRequest())


def test_ibm_enforces_catalog_page_limit() -> None:
    parser = IbmJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(30)],
                    total=31,
                    start_index=0,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_ibm_wraps_listing_request_failures() -> None:
    parser = IbmJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_ibm_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ibm"]
    assert isinstance(parser, IbmJobsParser)
    assert parser.base_url == settings.ibm_jobs_base_url
    assert parser.api_url == settings.ibm_jobs_api_url
    assert parser.max_pages == settings.ibm_jobs_max_pages
    assert parser.max_catalog_passes == settings.ibm_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "IBM", "filters": {}},
            "sources": ["ibm", "ibm"],
        }
    )
    assert request.sources == ["ibm"]


def test_ibm_jobs_render_as_direct_company_imports() -> None:
    job = IbmJobsParser().normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="ibm-125001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "IBM import"
    assert stored["id"] == "ibm-125001"
