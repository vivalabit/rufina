from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.accenture import AccentureJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    requisition_id = f"R00349{index:03d}"
    return {
        "guid": f"{requisition_id}_en",
        "requisitionId": requisition_id,
        "title": f"Cloud Platform Engineer {index}",
        "country": "Switzerland",
        "location": ["Zurich", "Basel"] if index == 0 else ["Zurich"],
        "feedCity": "Zurich",
        "postedDateText": "Posted 2 days ago",
        "updateDate": "2026-08-06T05:34:00.000-07:00",
        "employeeType": "Full-time",
        "jobScheduleDescription": "Full time",
        "careerLevel": "Team Lead/Consultant",
        "jobTypeDescription": "Mid-Level",
        "jobDescriptionClean": (
            "Build reliable cloud platforms.\nCollaborate with delivery teams."
        ),
        "qualificationClean": "Experience with Kubernetes and Terraform.",
        "jobDetailUrl": (
            "https://www.accenture.com/{0}/careers/jobdetails?"
            f"id={requisition_id}_en&title=Cloud+Platform+Engineer"
        ),
        "internalReferURL": (
            "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/"
            f"job/Zurich/Cloud-Platform-Engineer_{requisition_id}/apply"
        ),
    }


def payload(records: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {
        "data": records,
        "aggregations": [],
        "totalHits": {"total": total, "overMaxHits": "False"},
        "message": "Success",
    }


def test_accenture_fetches_every_page_and_normalizes_records() -> None:
    records = [listing_record(index) for index in range(5)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/accenture/elastic/findjobs"
        form = parse_qs(request.content.decode(), keep_blank_values=True)
        assert form["jobCountry"] == ["Switzerland"]
        assert form["countrySite"] == ["ch-en"]
        assert form["jobFilters"] == ["[]"]
        offset = int(form["startIndex"][0])
        page_size = int(form["maxResultSize"][0])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=payload(records[offset : offset + page_size], total=len(records)),
        )

    parser = AccentureJobsParser(
        base_url="https://www.accenture.test/ch-en/careers/jobsearch",
        api_url="https://www.accenture.test/api/accenture/elastic/findjobs",
        page_size=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 2, 4]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 5 Accenture vacancies across 3 API pages (5 listed)"
    )
    assert len(result.jobs) == 5
    first = result.jobs[0]
    assert first.source == "accenture"
    assert first.title == "Cloud Platform Engineer 0"
    assert first.company == "Accenture"
    assert first.location == "Zurich, Basel"
    assert first.url == (
        "https://www.accenture.test/ch-en/careers/jobdetails?id=R00349000_en"
    )
    assert first.apply_url == (
        "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/"
        "job/Zurich/Cloud-Platform-Engineer_R00349000/apply"
    )
    assert first.posted_at == "2026-08-06T05:34:00.000-07:00"
    assert first.employment_type == "Full-time"
    assert first.seniority == "Team Lead/Consultant"
    assert first.description == (
        "Build reliable cloud platforms.\nCollaborate with delivery teams.\n\n"
        "Qualifications\nExperience with Kubernetes and Terraform."
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["total_available"] == 5


def test_accenture_deduplicates_stable_job_ids() -> None:
    records = [listing_record(1), listing_record(1)]
    parser = AccentureJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload(records, total=2))
        )
    )

    result = parser.search(LinkedInSearchRequest(deduplicate=True))

    assert len(result.jobs) == 1


def test_accenture_rejects_invalid_jobs_payload() -> None:
    parser = AccentureJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"data": {}, "totalHits": {"total": 4}},
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid data"):
        parser.search(LinkedInSearchRequest())


def test_accenture_does_not_silently_truncate_above_page_limit() -> None:
    parser = AccentureJobsParser(
        max_pages=2,
        page_size=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=payload([listing_record(0), listing_record(1)], total=5),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_accenture_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["accenture"]
    assert isinstance(parser, AccentureJobsParser)
    assert parser.base_url == settings.accenture_jobs_base_url
    assert parser.api_url == settings.accenture_jobs_api_url
    assert parser.max_pages == settings.accenture_jobs_max_pages
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Accenture", "filters": {}},
            "sources": ["accenture", "accenture"],
        }
    )
    assert request.sources == ["accenture"]


def test_accenture_jobs_render_as_direct_company_imports() -> None:
    parser = AccentureJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="accenture-R00349001_en",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Accenture import"
    assert stored["id"] == "accenture-R00349001_en"
