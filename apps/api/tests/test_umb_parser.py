from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.umb import UmbJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

JOB_IDS = ("744000143231549", "744000141258139", "744000139948463")


def listing_record(
    index: int,
    *,
    country: str = "ch",
    job_id: str | None = None,
) -> dict[str, object]:
    resolved_id = job_id or JOB_IDS[index]
    city = "Alle" if index == 0 else "Cham"
    return {
        "id": resolved_id,
        "name": f"Senior System Engineer {index}",
        "uuid": f"publication-{index}",
        "refNumber": f"REF{index}",
        "company": {"identifier": "UMBAG1", "name": "UMB AG"},
        "releasedDate": f"2026-08-{13 - index:02d}T05:39:34.947Z",
        "location": {
            "city": city,
            "country": country,
            "remote": False,
            "hybrid": index == 0,
            "fullLocation": f"{city}, , Switzerland",
        },
        "department": {"id": "13020171", "label": "Customer Teams"},
        "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        "experienceLevel": {"id": "mid_senior_level", "label": "Mid-Senior Level"},
        "customField": [
            {"fieldLabel": "Experience Level", "valueLabel": "Senior"},
            {"fieldLabel": "Pensum", "valueLabel": "80% - 100%"},
            {"fieldLabel": "Standort", "valueLabel": "Region Zürich"},
        ],
        "visibility": "PUBLIC",
        "ref": f"https://api.smartrecruiters.com/v1/companies/UMBAG1/postings/{resolved_id}",
    }


def detail_record(index: int) -> dict[str, object]:
    record = listing_record(index)
    job_id = JOB_IDS[index]
    record.update(
        {
            "active": True,
            "postingUrl": (
                f"https://jobs.smartrecruiters.com/UMBAG1/{job_id}-senior-system-engineer-{index}"
            ),
            "applyUrl": (
                f"https://jobs.smartrecruiters.com/UMBAG1/{job_id}-"
                f"senior-system-engineer-{index}?oga=true"
            ),
            "jobAd": {
                "sections": {
                    "companyDescription": {
                        "title": "Unternehmensbeschreibung",
                        "text": "<p>UMB schafft Zeit.</p>",
                    },
                    "jobDescription": {
                        "title": "Stellenbeschreibung",
                        "text": "<ul><li>Cloud-Plattformen betreiben</li></ul>",
                    },
                    "qualifications": {
                        "title": "Qualifikationen",
                        "text": "<ul><li>Azure-Erfahrung</li></ul>",
                    },
                }
            },
            "compensation": {"max": 80000, "currency": "CHF", "period": "YEARLY"},
        }
    )
    return record


def catalog_payload(
    indexes: list[int],
    *,
    offset: int,
    total: int = 3,
) -> dict[str, object]:
    return {
        "offset": offset,
        "limit": 2,
        "totalFound": total,
        "content": [listing_record(index) for index in indexes],
    }


def test_umb_collects_every_page_and_enriches_smartrecruiters_details() -> None:
    requests: list[tuple[str, int | str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            assert request.url.params["limit"] == "2"
            offset = int(request.url.params["offset"])
            requests.append(("listing", offset))
            indexes = [0, 1] if offset == 0 else [2]
            return httpx.Response(
                200,
                json=catalog_payload(indexes, offset=offset),
                request=request,
            )
        job_id = request.url.path.rsplit("/", 1)[-1]
        index = JOB_IDS.index(job_id)
        requests.append(("detail", index))
        return httpx.Response(200, json=detail_record(index), request=request)

    parser = UmbJobsParser(
        api_url="https://api.smartrecruiters.com/v1/companies/UMBAG1/postings",
        page_size=2,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )
    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requests == [
        ("listing", 0),
        ("listing", 2),
        ("detail", 0),
        ("detail", 1),
        ("detail", 2),
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 UMB vacancies from 3 catalog records across 2 API requests"
    )
    assert len(result.jobs) == 3

    job = result.jobs[0]
    assert job.source == "umb"
    assert job.title == "Senior System Engineer 0"
    assert job.company == "UMB AG"
    assert job.location == "Region Zürich (Hybrid)"
    assert job.url == (
        "https://jobs.smartrecruiters.com/UMBAG1/744000143231549-senior-system-engineer-0"
    )
    assert job.apply_url == f"{job.url}?oga=true"
    assert job.posted_at == "2026-08-13T05:39:34.947Z"
    assert job.employment_type == "Full-time (80% - 100%)"
    assert job.seniority == "Senior"
    assert job.description == (
        "Unternehmensbeschreibung\nUMB schafft Zeit.\n\n"
        "Stellenbeschreibung\n- Cloud-Plattformen betreiben\n\n"
        "Qualifikationen\n- Azure-Erfahrung"
    )
    assert job.salary == "Up to 80,000 CHF yearly"
    assert job.salary_min is None
    assert job.salary_max == 80000
    assert job.salary_currency == "CHF"
    assert job.salary_unit == "yearly"
    assert job.raw["listing_offset"] == 0
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["active"] is True


def test_umb_preserves_listing_when_one_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            return httpx.Response(
                200,
                json={
                    "offset": 0,
                    "limit": 100,
                    "totalFound": 1,
                    "content": [listing_record(0)],
                },
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        UmbJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior System Engineer 0"
    assert job.location == "Region Zürich (Hybrid)"
    assert job.url == "https://jobs.smartrecruiters.com/UMBAG1/744000143231549"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {"offset": 0, "limit": 100, "totalFound": 1, "content": "invalid"},
            "invalid content",
        ),
        (
            {
                "offset": 0,
                "limit": 100,
                "totalFound": 1,
                "content": [listing_record(0, country="de")],
            },
            "non-Swiss vacancy",
        ),
        (
            {
                "offset": 0,
                "limit": 100,
                "totalFound": 2,
                "content": [listing_record(0), listing_record(0)],
            },
            "duplicate vacancy IDs",
        ),
    ],
)
def test_umb_rejects_invalid_catalog(payload: object, message: str) -> None:
    parser = UmbJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_umb_max_pages_prevents_silent_catalog_truncation() -> None:
    parser = UmbJobsParser(
        max_pages=1,
        page_size=2,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=catalog_payload([0, 1], offset=0),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="limit of 1 pages"):
        parser.search(LinkedInSearchRequest())


def test_umb_wraps_catalog_request_failures() -> None:
    parser = UmbJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_umb_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["umb"]
    assert isinstance(parser, UmbJobsParser)
    assert parser.base_url == settings.umb_jobs_base_url
    assert parser.api_url == settings.umb_jobs_api_url
    assert parser.max_pages == settings.umb_jobs_max_pages
    assert parser.max_catalog_passes == settings.umb_jobs_max_catalog_passes
    assert parser.detail_workers == settings.umb_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "UMB", "filters": {}},
            "sources": ["umb", "umb"],
        }
    )
    assert request.sources == ["umb"]


def test_umb_jobs_render_as_direct_company_imports() -> None:
    record = listing_record(0)
    record["detail"] = detail_record(0)
    parsed = UmbJobsParser().normalize_job(record)

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="umb-744000143231549",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "umb-744000143231549"
    assert stored["logo"] == "company"
    assert stored["department"] == "UMB AG import"
    assert stored["company"] == "UMB AG"
