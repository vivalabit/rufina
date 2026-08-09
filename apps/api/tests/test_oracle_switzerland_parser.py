from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.oracle_switzerland import (
    ORACLE_SWITZERLAND_LOCATION_ID,
    OracleSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, secondary_swiss: bool = False) -> dict[str, object]:
    record: dict[str, object] = {
        "Id": str(335_000 + index),
        "Title": f"Cloud Engineer {index}",
        "PostedDate": "2026-08-08",
        "PrimaryLocation": "ZURICH, Switzerland",
        "PrimaryLocationCountry": "CH",
        "ShortDescriptionStr": "Build secure cloud services.",
        "JobSchedule": "Full time",
        "ManagerLevel": "Individual Contributor",
        "secondaryLocations": [],
        "otherWorkLocations": [],
        "workLocation": [],
    }
    if secondary_swiss:
        record["PrimaryLocation"] = "United States"
        record["PrimaryLocationCountry"] = "US"
        record["secondaryLocations"] = [
            {
                "Name": "Switzerland",
                "CountryCode": "CH",
                "GeographyId": int(ORACLE_SWITZERLAND_LOCATION_ID),
            }
        ]
    return record


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int,
    offset: int,
) -> dict[str, object]:
    return {
        "items": [
            {
                "Offset": offset,
                "Limit": 25,
                "TotalJobsCount": total,
                "requisitionList": records,
            }
        ]
    }


def detail_payload(record: dict[str, object]) -> dict[str, object]:
    return {
        "items": [
            {
                **record,
                "ExternalPostedStartDate": "2026-08-08T07:49:34+00:00",
                "RequisitionType": "Professional",
                "JobLevel": "IC4",
                "ExternalDescriptionStr": "<p>Design &amp; build cloud systems.</p>",
                "ExternalResponsibilitiesStr": (
                    "<ul><li>Own services</li><li>Improve reliability</li></ul>"
                ),
                "ExternalQualificationsStr": "<p>Career Level - IC4</p>",
                "CorporateDescriptionStr": "<p>Oracle builds cloud technology.</p>",
            }
        ]
    }


def test_oracle_switzerland_fetches_complete_filtered_catalog_and_details() -> None:
    records = [listing_record(index, secondary_swiss=index == 0) for index in range(26)]
    requested_offsets: list[int] = []
    detail_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            finder = request.url.params["finder"]
            job_id = finder.split('Id="', 1)[1].split('"', 1)[0]
            detail_ids.append(job_id)
            record = next(item for item in records if item["Id"] == job_id)
            return httpx.Response(200, json=detail_payload(record))

        assert request.url.path.endswith("/recruitingCEJobRequisitions")
        assert request.url.params["onlyData"] == "true"
        finder = request.url.params["finder"]
        assert "siteNumber=CX_45001" in finder
        assert f"locationId={ORACLE_SWITZERLAND_LOCATION_ID}" in finder
        assert f"selectedLocationsFacet={ORACLE_SWITZERLAND_LOCATION_ID}" in finder
        finder_params = parse_qs(finder.replace("findReqs;", "").replace(",", "&"))
        offset = int(finder_params["offset"][0])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=listing_payload(records[offset : offset + 25], total=26, offset=offset),
        )

    parser = OracleSwitzerlandJobsParser(
        base_url="https://careers.oracle.test/jobs?location=Switzerland",
        api_url="https://oracle.test/hcmRestApi/resources/latest",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 25]
    assert sorted(detail_ids) == sorted(str(335_000 + index) for index in range(26))
    assert result.status == "completed"
    assert result.message == (
        "Scanned 26 Oracle Switzerland vacancies from 26 catalog records across 2 API page requests"
    )
    assert len(result.jobs) == 26
    first = result.jobs[0]
    assert first.source == "oracle_switzerland"
    assert first.title == "Cloud Engineer 0"
    assert first.company == "Oracle"
    assert first.location == "United States; Switzerland"
    assert first.url == "https://careers.oracle.com/en/sites/jobsearch/job/335000"
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-08T07:49:34+00:00"
    assert first.employment_type == "Full time"
    assert first.seniority == "IC4"
    assert first.description == (
        "Description\nDesign & build cloud systems.\n\n"
        "Responsibilities\n- Own services\n- Improve reliability\n\n"
        "Qualifications\nCareer Level - IC4\n\n"
        "About Oracle\nOracle builds cloud technology."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 0
    assert first.raw["total_available"] == 26


def test_oracle_switzerland_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(26)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            finder = request.url.params["finder"]
            job_id = finder.split('Id="', 1)[1].split('"', 1)[0]
            record = next(item for item in records if item["Id"] == job_id)
            return httpx.Response(200, json=detail_payload(record))
        finder = request.url.params["finder"]
        params = parse_qs(finder.replace("findReqs;", "").replace(",", "&"))
        offset = int(params["offset"][0])
        requested_offsets.append(offset)
        if offset == 0:
            page = records[:25]
        elif requested_offsets.count(25) == 1:
            page = [records[24]]
        else:
            page = records[25:]
        return httpx.Response(200, json=listing_payload(page, total=26, offset=offset))

    parser = OracleSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 25, 0, 25]
    assert len(result.jobs) == 26
    assert result.message.endswith("across 4 API page requests")


def test_oracle_switzerland_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            return httpx.Response(503)
        return httpx.Response(200, json=listing_payload([record], total=1, offset=0))

    parser = OracleSwitzerlandJobsParser(transport=httpx.MockTransport(handler))

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].description == "Build secure cloud services."
    assert "503 Service Unavailable" in str(result.jobs[0].raw["detail_error"])


@pytest.mark.parametrize(
    "record",
    [
        {**listing_record(1), "Id": "not-a-number"},
        {**listing_record(1), "PrimaryLocationCountry": "US"},
    ],
)
def test_oracle_switzerland_rejects_invalid_or_non_swiss_payload(
    record: dict[str, object],
) -> None:
    parser = OracleSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=listing_payload([record], total=1, offset=0))
        )
    )

    with pytest.raises(DirectCompanyRequestError):
        parser.search(LinkedInSearchRequest())


def test_oracle_switzerland_enforces_catalog_page_limit() -> None:
    parser = OracleSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([listing_record(1)], total=26, offset=0),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_oracle_switzerland_wraps_listing_request_failures() -> None:
    parser = OracleSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_oracle_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["oracle_switzerland"]
    assert isinstance(parser, OracleSwitzerlandJobsParser)
    assert parser.base_url == settings.oracle_switzerland_jobs_base_url
    assert parser.api_url == settings.oracle_switzerland_jobs_api_url
    assert parser.max_pages == settings.oracle_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.oracle_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.oracle_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Oracle Switzerland", "filters": {}},
            "sources": ["oracle_switzerland", "oracle_switzerland"],
        }
    )
    assert request.sources == ["oracle_switzerland"]


def test_oracle_switzerland_jobs_render_as_direct_company_imports() -> None:
    parsed = OracleSwitzerlandJobsParser().normalize_job(listing_record(1))

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="oracle_switzerland-335001",
        added_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "oracle_switzerland-335001"
    assert stored["logo"] == "company"
    assert stored["department"] == "Oracle Switzerland import"
    assert stored["company"] == "Oracle"
