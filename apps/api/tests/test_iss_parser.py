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
from app.services.parsers.companies.iss import IssJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int) -> dict[str, object]:
    publication_id = 4_000_000 + index
    return {
        "order": f"2026-08-08_{3_100_000 + index}",
        "id": index,
        "jobTitle": f"Facility Engineer {index} 100%",
        "link": f"/iss/job/details/{publication_id}/",
        "fullTextSearch": f"Complete listing description for vacancy {index}.",
        "publicDate": "08.08.2026",
        "startDate": 1_786_140_559 + index,
        "newFlag": "NEW" if index == 0 else "",
        "locationFreeText": "Zürich",
        "jobCategory": "Technik",
        "jobCategoryId": "JC20",
        "employmentType": "Vollzeit",
        "employmentTypeId": "ET30",
        "limitation": "unbefristet",
        "limitationId": "LI20",
        "function": "mit Kaderfunktion",
        "functionId": "FU10",
        "region": "Zürich",
        "regionId": "ZH",
        "zip": "Zürich",
        "zipId": "ZH-01",
    }


def listing_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "jobs": records,
        "employmentType": [
            {"id": "ET20", "value": "Teilzeit", "count": 0},
            {"id": "ET30", "value": "Vollzeit", "count": len(records)},
        ],
    }


def detail_html(record: dict[str, object]) -> str:
    publication_id = str(record["link"]).rstrip("/").rsplit("/", maxsplit=1)[-1]
    posting = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "identifier": {
            "@type": "PropertyValue",
            "name": "ISS Facility Services AG",
            "value": f"REQ-{publication_id}",
        },
        "title": f"Facility Engineer {publication_id}",
        "description": (
            "Facility Engineer 100%<br/><br/>- Build reliable systems<br/>- Support users"
        ),
        "hiringOrganization": {
            "@type": "Organization",
            "name": "ISS Facility Services AG",
        },
        "datePosted": "2026-08-08T10:15:00+02:00",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Zürich",
                "addressRegion": "ZH",
                "postalCode": "8005",
                "addressCountry": "CH",
            },
        },
        "employmentType": "FULL_TIME",
    }
    return (
        "<html><head>"
        f'<link rel="canonical" href="https://live.solique.test/iss/job/details/{publication_id}/">'
        f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        "</head><body>"
        '<div class="short-description">Join a dependable facility team.</div>'
        '<div class="workload">100%</div>'
        f'<a class="apply-btn" href="https://iss-candidate.test/apply/{publication_id}">Apply</a>'
        "</body></html>"
    )


def test_iss_fetches_full_catalog_and_enriches_every_record() -> None:
    records = [listing_record(index) for index in range(12)]
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/ISS/de/ajax/":
            return httpx.Response(200, json=listing_payload(records))
        requested_details.append(request.url.path)
        publication_id = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if publication_id in str(item["link"]))
        return httpx.Response(200, text=detail_html(record))

    parser = IssJobsParser(
        base_url="https://www.ch.issworld.test/de-ch/karriere/offene-stellen",
        api_url="https://live.solique.test/ISS/de/ajax/",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(requested_details) == 12
    assert result.status == "completed"
    assert result.message == "Scanned 12 ISS vacancies from the Solique catalog"
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "iss"
    assert first.title == "Facility Engineer 0 100%"
    assert first.company == "ISS Facility Services AG"
    assert first.location == "Zürich"
    assert first.url == "https://live.solique.test/iss/job/details/4000000/"
    assert first.apply_url == "https://iss-candidate.test/apply/4000000"
    assert first.posted_at == "2026-08-08T10:15:00+02:00"
    assert first.employment_type == "Vollzeit, 100%"
    assert first.seniority == "mit Kaderfunktion"
    assert first.description == (
        "Join a dependable facility team.\n\n"
        "Facility Engineer 100%\n\n- Build reliable systems\n- Support users"
    )
    assert isinstance(first.raw["detail"], dict)
    assert first.raw["detail"]["job_posting"]["employmentType"] == "FULL_TIME"


def test_iss_preserves_complete_listing_when_detail_request_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ISS/de/ajax/":
            return httpx.Response(200, json=listing_payload([record]))
        return httpx.Response(503, text="temporarily unavailable")

    parser = IssJobsParser(transport=httpx.MockTransport(handler))

    result = parser.search(LinkedInSearchRequest())

    job = result.jobs[0]
    assert job.description == "Complete listing description for vacancy 1."
    assert job.url == "https://live.solique.ch/iss/job/details/4000001/"
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_iss_rejects_invalid_jobs_payload() -> None:
    parser = IssJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"jobs": {}}))
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        parser.search(LinkedInSearchRequest())


def test_iss_rejects_catalog_that_disagrees_with_filter_totals() -> None:
    record = listing_record(1)
    payload = listing_payload([record])
    payload["employmentType"] = [{"id": "ET30", "value": "Vollzeit", "count": 2}]
    parser = IssJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="employment-type totals"):
        parser.search(LinkedInSearchRequest())


def test_iss_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["iss"]
    assert isinstance(parser, IssJobsParser)
    assert parser.base_url == settings.iss_jobs_base_url
    assert parser.api_url == settings.iss_jobs_api_url
    assert parser.detail_workers == settings.iss_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ISS Schweiz", "filters": {}},
            "sources": ["iss", "iss"],
        }
    )
    assert request.sources == ["iss"]


def test_iss_jobs_render_as_direct_company_imports() -> None:
    parser = IssJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="iss-4000001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "ISS Schweiz import"
    assert stored["id"] == "iss-4000001"
