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
from app.services.parsers.companies.endress_hauser_switzerland import (
    EndressHauserSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy(
    job_id: str,
    title: str,
    *,
    city: str = "Reinach",
) -> dict[str, object]:
    requisition_id = job_id.split("-", maxsplit=1)[0]
    return {
        "language": "en_US",
        "isActive": True,
        "jobId": job_id,
        "link": (f"https://careers.endress.test/job-invite/{requisition_id}/?locale=en_US"),
        "title": title,
        "description": (
            "<p><strong>What is the role about?</strong></p>"
            "<p>Build reliable automation systems.</p>"
            "<ul><li>Collaborate with the engineering team.</li></ul>"
        ),
        "datePosted": "2026-08-03T14:24:00Z",
        "salaryMin": 100000,
        "salaryMax": 120000.0,
        "currency": "CHF",
        "department": "Engineering",
        "jobLevel": "Professional",
        "jobType": "Permanent",
        "workHours": "Full-time",
        "applyUrl": (
            "https://career5.successfactors.eu/career?company=endress&"
            f"career_job_req_id={requisition_id}&career_ns=job_application&"
            "lang=en_US"
        ),
        "division": "Endress+Hauser Flow Switzerland",
        "recruiter": {
            "firstName": "Ada",
            "lastName": "Lovelace",
            "photo": {"data": "large-base64-payload", "mimeType": "image/jpeg"},
        },
        "addresses": [
            {
                "city": city,
                "postalCode": "4153",
                "country": "Switzerland",
                "street": "Christoph Merian-Ring 4",
            }
        ],
        "hiringOrganisation": {
            "name": "Endress+Hauser Flow Switzerland",
        },
    }


def api_response(records: list[dict[str, object]], total: int) -> dict[str, object]:
    return {
        "@odata.context": "https://search.example/$metadata#docs(*)",
        "@odata.count": total,
        "value": records,
    }


def test_endress_hauser_switzerland_scans_every_page_and_normalizes_jobs() -> None:
    records = [
        vacancy("41541-en_US", "Application Engineer (f/m/d)"),
        vacancy("41539-en_US", "Supply Chain Support Engineer (f/m/d)"),
        vacancy("41537-en_US", "PCB Design Engineer (m/w/d)", city="Basel"),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        offset = body["skip"]
        page_size = body["top"]
        return httpx.Response(
            200,
            json=api_response(records[offset : offset + page_size], len(records)),
        )

    parser = EndressHauserSwitzerlandJobsParser(
        base_url="https://careers.endress.test/Switzerland/content/search/",
        api_url="https://api.endress.test/search",
        customer_id="eh-test",
        api_key="public-test-key",
        page_size=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Endress+Hauser Switzerland vacancies across 2 API pages (3 listed)"
    )
    assert len(result.jobs) == 3
    assert len(requests) == 2
    assert [json.loads(request.content)["skip"] for request in requests] == [0, 2]
    first_request = requests[0]
    first_payload = json.loads(first_request.content)
    assert first_request.url == "https://api.endress.test/search"
    assert first_request.headers["customerid"] == "eh-test"
    assert first_request.headers["x-api-key"] == "public-test-key"
    assert first_request.headers["internal"] == "false"
    assert first_request.headers["privatejobboard"] == "false"
    assert first_request.headers["referer"] == parser.base_url
    assert first_payload["top"] == 2
    assert first_payload["orderby"] == "datePosted desc"
    assert "addresses/any(jt: jt/country eq 'Switzerland')" in first_payload["filter"]
    assert "language eq 'en_US'" in first_payload["filter"]

    first = result.jobs[0]
    assert first.source == "endress_hauser_switzerland"
    assert first.title == "Application Engineer (f/m/d)"
    assert first.company == "Endress+Hauser Flow Switzerland"
    assert first.location == "Reinach, Switzerland"
    assert first.url == records[0]["link"]
    assert first.apply_url == records[0]["applyUrl"]
    assert first.posted_at == "2026-08-03T14:24:00Z"
    assert first.employment_type == "Full-time · Permanent"
    assert first.seniority == "Professional"
    assert first.salary_min == 100000
    assert first.salary_max == 120000
    assert first.salary_currency == "CHF"
    assert first.description == (
        "What is the role about?\n"
        "Build reliable automation systems.\n"
        "• Collaborate with the engineering team."
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["raw_fields_removed"] == ["recruiter.photo"]
    assert "photo" not in first.raw["recruiter"]
    assert result.jobs[2].raw["listing_page"] == 2


def test_endress_hauser_switzerland_deduplicates_when_requested() -> None:
    record = vacancy("41541-en_US", "Application Engineer (f/m/d)")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=api_response([record, record], 2))
    )
    parser = EndressHauserSwitzerlandJobsParser(transport=transport)

    deduplicated = parser.search(LinkedInSearchRequest(deduplicate=True))
    complete = parser.search(LinkedInSearchRequest(deduplicate=False))

    assert len(deduplicated.jobs) == 1
    assert len(complete.jobs) == 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"@odata.count": "1", "value": []},
        {"@odata.count": 1, "jobs": []},
        {"@odata.count": 1, "value": [{}]},
    ],
)
def test_endress_hauser_switzerland_rejects_invalid_payload(payload: object) -> None:
    parser = EndressHauserSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="jobs response"):
        parser.search(LinkedInSearchRequest())


def test_endress_hauser_switzerland_rejects_incomplete_page() -> None:
    parser = EndressHauserSwitzerlandJobsParser(
        page_size=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=api_response(
                    [vacancy("41541-en_US", "Application Engineer")],
                    2,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="returned 1 vacancies"):
        parser.search(LinkedInSearchRequest())


def test_endress_hauser_switzerland_enforces_page_limit() -> None:
    parser = EndressHauserSwitzerlandJobsParser(
        max_pages=1,
        page_size=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=api_response(
                    [
                        vacancy("41541-en_US", "Application Engineer"),
                        vacancy("41539-en_US", "Support Engineer"),
                    ],
                    3,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_endress_hauser_switzerland_wraps_api_failures() -> None:
    parser = EndressHauserSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_endress_hauser_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["endress_hauser_switzerland"]
    assert isinstance(parser, EndressHauserSwitzerlandJobsParser)
    assert parser.base_url == settings.endress_hauser_switzerland_jobs_base_url
    assert parser.api_url == settings.endress_hauser_switzerland_jobs_api_url
    assert parser.customer_id == settings.endress_hauser_switzerland_jobs_customer_id
    assert parser.api_key == settings.endress_hauser_switzerland_jobs_api_key
    assert parser.max_pages == settings.endress_hauser_switzerland_jobs_max_pages
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Endress+Hauser Switzerland", "filters": {}},
            "sources": [
                "endress_hauser_switzerland",
                "endress_hauser_switzerland",
            ],
        }
    )
    assert request.sources == ["endress_hauser_switzerland"]


def test_endress_hauser_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = EndressHauserSwitzerlandJobsParser()
    job = parser.normalize_job(vacancy("41541-en_US", "Application Engineer (f/m/d)"))
    stored = parsed_job_to_stored_job(
        job,
        job_id="endress_hauser_switzerland-41541-en_US",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Endress+Hauser Switzerland import"
    assert stored["id"] == "endress_hauser_switzerland-41541-en_US"
