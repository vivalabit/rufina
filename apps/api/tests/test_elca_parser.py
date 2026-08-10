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
from app.services.parsers.companies.elca import (
    ELCA_SWITZERLAND_LOCATION_ID,
    ElcaJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    return {
        "Id": str(2700 + index),
        "Title": f"Cloud Engineer {index}",
        "PostedDate": "2026-08-04",
        "PrimaryLocation": "Zurich, Switzerland",
        "PrimaryLocationCountry": "CH",
        "ShortDescriptionStr": "Build secure Swiss cloud services.",
        "JobSchedule": "Full time",
        "ManagerLevel": None,
    }


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
                "ExternalPostedStartDate": "2026-08-04T05:23:35+00:00",
                "RequisitionType": "Senior Positions",
                "JobLevel": None,
                "JobSchedule": "Full time",
                "LegalEmployer": "ELCA Informatique SA",
                "Organization": None,
                "ExternalDescriptionStr": "<p>Design &amp; build cloud systems.</p>",
                "ExternalResponsibilitiesStr": (
                    "<ul><li>Own services</li><li>Improve reliability</li></ul>"
                ),
                "ExternalQualificationsStr": "<p>Strong Python skills.</p>",
                "CorporateDescriptionStr": "<p>ELCA builds Swiss technology.</p>",
                "secondaryLocations": [{"Name": "Bern, Switzerland", "CountryCode": "CH"}],
                "otherWorkLocations": [],
                "workLocation": [
                    {
                        "LocationName": "Basel",
                        "TownOrCity": "Basel",
                        "Country": "CH",
                    }
                ],
            }
        ]
    }


def test_elca_fetches_complete_swiss_catalog_and_details() -> None:
    records = [listing_record(index) for index in range(26)]
    requested_offsets: list[int] = []
    detail_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            finder = request.url.params["finder"]
            finder_params = parse_qs(finder.replace("ById;", "").replace(",", "&"))
            job_id = finder_params["Id"][0]
            assert finder_params["siteNumber"] == ["CX_1"]
            detail_ids.append(job_id)
            record = next(item for item in records if item["Id"] == job_id)
            return httpx.Response(200, json=detail_payload(record))

        assert request.url.path.endswith("/recruitingCEJobRequisitions")
        assert request.url.params["onlyData"] == "true"
        assert request.url.params["expand"] == "requisitionList"
        finder = request.url.params["finder"]
        finder_params = parse_qs(finder.replace("findReqs;", "").replace(",", "&"))
        assert finder_params["siteNumber"] == ["CX_1"]
        assert finder_params["selectedLocationsFacet"] == [ELCA_SWITZERLAND_LOCATION_ID]
        assert finder_params["sortBy"] == ["POSTING_DATES_DESC"]
        offset = int(finder_params["offset"][0])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=listing_payload(records[offset : offset + 25], total=26, offset=offset),
        )

    parser = ElcaJobsParser(
        base_url=("https://elca.test/hcmUI/CandidateExperience/en/sites/CX_1/jobs"),
        api_url="https://elca.test/hcmRestApi/resources/latest",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 25]
    assert sorted(detail_ids) == sorted(str(2700 + index) for index in range(26))
    assert result.status == "completed"
    assert result.message == (
        "Scanned 26 ELCA vacancies from 26 Swiss catalog records across 2 API page requests"
    )
    assert len(result.jobs) == 26
    first = result.jobs[0]
    assert first.source == "elca"
    assert first.title == "Cloud Engineer 0"
    assert first.company == "ELCA Informatique SA"
    assert first.location == "Zurich, Switzerland; Bern, Switzerland"
    assert first.url == ("https://elca.test/hcmUI/CandidateExperience/en/sites/CX_1/job/2700")
    assert first.apply_url == (
        "https://elca.test/hcmUI/CandidateExperience/en/sites/CX_1/job/2700/apply/email"
    )
    assert first.posted_at == "2026-08-04T05:23:35+00:00"
    assert first.employment_type == "Full time"
    assert first.seniority == "Senior Positions"
    assert first.description == (
        "Description\nDesign & build cloud systems.\n\n"
        "Responsibilities\n- Own services\n- Improve reliability\n\n"
        "Qualifications\nStrong Python skills.\n\n"
        "About ELCA\nELCA builds Swiss technology."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 26


def test_elca_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(26)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        finder = request.url.params["finder"]
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            params = parse_qs(finder.replace("ById;", "").replace(",", "&"))
            record = next(item for item in records if item["Id"] == params["Id"][0])
            return httpx.Response(200, json=detail_payload(record))

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

    parser = ElcaJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert requested_offsets == [0, 25, 0, 25]
    assert len(result.jobs) == 26
    assert result.message.endswith("across 4 API page requests")


def test_elca_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            return httpx.Response(503)
        return httpx.Response(200, json=listing_payload([record], total=1, offset=0))

    job = (
        ElcaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.company == "ELCA"
    assert job.description == "Build secure Swiss cloud services."
    assert job.apply_url and job.apply_url.endswith("/job/2701/apply/email")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "record",
    [
        {**listing_record(1), "Id": "not-a-number"},
        {**listing_record(1), "PrimaryLocationCountry": "IT"},
    ],
)
def test_elca_rejects_invalid_or_non_swiss_payload(
    record: dict[str, object],
) -> None:
    parser = ElcaJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=listing_payload([record], total=1, offset=0),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError):
        parser.search(LinkedInSearchRequest())


def test_elca_enforces_catalog_page_limit() -> None:
    parser = ElcaJobsParser(
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


def test_elca_wraps_listing_request_failures() -> None:
    parser = ElcaJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_elca_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["elca"]
    assert isinstance(parser, ElcaJobsParser)
    assert parser.base_url == settings.elca_jobs_base_url
    assert parser.api_url == settings.elca_jobs_api_url
    assert parser.max_pages == settings.elca_jobs_max_pages
    assert parser.max_catalog_passes == settings.elca_jobs_max_catalog_passes
    assert parser.detail_workers == settings.elca_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ELCA", "filters": {}},
            "sources": ["elca", "elca"],
        }
    )
    assert request.sources == ["elca"]


def test_elca_jobs_render_as_direct_company_imports() -> None:
    parsed = ElcaJobsParser().normalize_job(listing_record(1))

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="elca-2701",
        added_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "elca-2701"
    assert stored["logo"] == "company"
    assert stored["department"] == "ELCA import"
    assert stored["company"] == "ELCA"
