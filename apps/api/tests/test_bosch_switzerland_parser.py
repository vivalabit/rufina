from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bosch_switzerland import (
    BoschSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

API_HOST = "bosch-i3-caas-api.e-spirit.cloud"
API_KEY = "2b760fb7-49ef-4e83-b4ba-9c3a8d185e5e"


def config_html(*, api_key: str = API_KEY) -> str:
    return f"""
    <html><script>
      window.EXTERNAL_CONFIG={{
        jobsApi:{{
          baseUrl:"https://{API_HOST}",
          tenant:"bosch-i3-prod",
          project:"bosch-de",
          collection:"jobs",
          apiKey:"{api_key}"
        }},
        jobAdLinkPrefix:"https://jobs.bosch.com/en/job/",
      }};
    </script></html>
    """


def listing(job_id: int, *, country: str = "ch") -> dict[str, Any]:
    reference = f"REF{job_id}G"
    title = f"Automation Engineer (w/m/div.) {reference}"
    return {
        "_id": reference,
        "name": title,
        "location": {
            "country": country,
            "city": "Frauenfeld",
            "workLocation": "Frauenfeld",
            "remote": False,
            "hybrid": True,
        },
        "refNumber": reference,
        "jobUrl": f"{reference}-automation-engineer-w-m-div-{reference.lower()}",
        "releasedDate": "2026-08-12T06:52:45.413Z",
        "function": {"id": "engineering", "label": "Engineering"},
        "language": {"code": "de", "label": "Deutsch"},
        "positionType": {
            "valueId": "professional",
            "valueLabel": "Berufserfahrene",
        },
        "country": {"valueId": country, "valueLabel": "Schweiz"},
        "type_of_contract": {
            "valueId": "permanent",
            "valueLabel": "Unbefristet",
        },
        "working_hours": {"valueId": "full", "valueLabel": "Vollzeit"},
        "legal_entity": {
            "valueId": "sia",
            "valueLabel": "sia Abrasives Industries AG",
        },
        "work_mode": "hybrid",
    }


def detail(
    job_id: int,
    *,
    country: str = "ch",
    posting_id: int | None = None,
    apply_host: str = "jobs.smartrecruiters.com",
) -> dict[str, Any]:
    reference = f"REF{job_id}G"
    numeric_id = str(posting_id or (744000000000000 + job_id))
    slug = f"{reference}-automation-engineer-w-m-div-{reference.lower()}"
    return {
        "_id": f"{reference}_de",
        "releasedDate": "2026-08-12T06:52:45.413Z",
        "positionType": {
            "valueId": "professional",
            "valueLabel": "Berufserfahrene",
        },
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "title": "Unternehmensbeschreibung",
                    "text": "<p>Bei Bosch gestalten wir Zukunft.</p>",
                },
                "jobDescription": {
                    "title": "Stellenbeschreibung",
                    "text": "<p>Build reliable systems.</p><ul><li>Own automation.</li></ul>",
                },
                "qualifications": {
                    "title": "Qualifikationen",
                    "text": "<p>Engineering experience.</p>",
                },
                "additionalInformation": {
                    "title": "Zusätzliche Informationen",
                    "text": "<p>Flexible working.</p>",
                },
            }
        },
        "language": {"code": "de", "label": "Deutsch"},
        "experienceLevel": {"id": "experienced", "label": "Berufserfahrene"},
        "function": {"id": "engineering", "label": "Engineering"},
        "jobUrl": slug,
        "company": {"identifier": "BoschGroup", "name": "Bosch Group"},
        "id": numeric_id,
        "visibility": "PUBLIC",
        "active": True,
        "defaultJobAd": True,
        "customField": [
            {
                "valueId": "sia",
                "valueLabel": "sia Abrasives Industries AG",
                "fieldLabel": "Rechtseinheit (ausgeschrieben)",
                "fieldId": "586a9995e4b0daa006ae1078",
            },
            {
                "valueId": country,
                "valueLabel": "Schweiz",
                "fieldLabel": "Land / Region",
                "fieldId": "COUNTRY",
            },
        ],
        "typeOfEmployment": {"id": "permanent", "label": "Vollzeit"},
        "refNumber": reference,
        "applyUrl": (f"https://{apply_host}/BoschGroup/{numeric_id}-automation-engineer?oga=true"),
        "name": f"Automation Engineer (w/m/div.) {reference}",
        "location": {
            "country": country,
            "country_abbr": country,
            "city": "Frauenfeld",
            "region": "TG",
            "fullLocation": "Frauenfeld, TG, Switzerland",
        },
        "postingUrl": (
            f"https://jobs.smartrecruiters.com/BoschGroup/{numeric_id}-automation-engineer"
        ),
    }


def listing_payload(records: list[dict[str, Any]], *, total: int) -> dict[str, Any]:
    return {
        "_returned": 1,
        "_embedded": {
            "rh:result": [
                {
                    "meta": [{"count": total}],
                    "data": records,
                }
            ]
        },
    }


def detail_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_id": "bosch-de.jobs.content",
        "_returned": len(records),
        "_embedded": records,
    }


def catalog_handler(
    listings: list[dict[str, Any]],
    details: list[dict[str, Any]],
    *,
    requested_pages: list[tuple[str, int]] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "jobs.bosch.com":
            return httpx.Response(200, text=config_html())

        assert request.url.host == API_HOST
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        page_number = int(request.url.params["page"])
        page_size = int(request.url.params["pagesize"])
        start = (page_number - 1) * page_size
        if request.url.path.endswith("/_aggrs/get_jobs"):
            if requested_pages is not None:
                requested_pages.append(("listing", page_number))
            variables = json.loads(request.url.params["avars"])
            assert variables == {
                "country": ["ch"],
                "sort": {"releasedDate": -1},
                "page_language": "en",
            }
            return httpx.Response(
                200,
                json=listing_payload(
                    listings[start : start + page_size],
                    total=len(listings),
                ),
            )

        if requested_pages is not None:
            requested_pages.append(("detail", page_number))
        assert json.loads(request.url.params["filter"]) == {"location.country": "ch"}
        return httpx.Response(
            200,
            json=detail_payload(details[start : start + page_size]),
        )

    return httpx.MockTransport(handler)


def test_bosch_scans_every_country_page_and_normalizes_full_details() -> None:
    listings = [listing(job_id) for job_id in (101, 102, 103)]
    details = [detail(job_id) for job_id in (101, 102, 103)]
    requested_pages: list[tuple[str, int]] = []
    parser = BoschSwitzerlandJobsParser(
        page_size=2,
        page_workers=2,
        transport=catalog_handler(
            listings,
            details,
            requested_pages=requested_pages,
        ),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert sorted(requested_pages) == [
        ("detail", 1),
        ("detail", 2),
        ("listing", 1),
        ("listing", 2),
    ]
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 verified Bosch Switzerland vacancies from 3 CaaS country "
        "records across 4 API page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "bosch_switzerland"
    assert first.title == "Automation Engineer (w/m/div.) REF101G"
    assert first.company == "sia Abrasives Industries AG"
    assert first.location == "Frauenfeld, TG, Switzerland"
    assert first.url == (
        "https://jobs.bosch.com/en/job/REF101G-automation-engineer-w-m-div-ref101g"
    )
    assert first.apply_url == (
        "https://jobs.smartrecruiters.com/BoschGroup/744000000000101-automation-engineer?oga=true"
    )
    assert first.posted_at == "2026-08-12"
    assert first.employment_type == "Full Time"
    assert first.seniority == "Berufserfahrene"
    assert first.description and "Own automation." in first.description
    assert first.raw["work_mode"] == "hybrid"
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3


def test_bosch_retries_shifted_pages_until_all_ids_match() -> None:
    first_listing_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_listing_calls
        if request.url.host == "jobs.bosch.com":
            return httpx.Response(200, text=config_html())
        page = int(request.url.params["page"])
        if request.url.path.endswith("/_aggrs/get_jobs"):
            if page == 1:
                first_listing_calls += 1
                records = [listing(101), listing(102)]
            else:
                records = [listing(102 if first_listing_calls == 1 else 103)]
            return httpx.Response(200, json=listing_payload(records, total=3))
        details = [detail(101), detail(102)] if page == 1 else [detail(103)]
        return httpx.Response(200, json=detail_payload(details))

    parser = BoschSwitzerlandJobsParser(
        page_size=2,
        page_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_listing_calls == 2
    assert result.message.endswith("across 8 API page requests in 2 catalog pass(es)")


def test_bosch_rejects_non_swiss_listing() -> None:
    parser = BoschSwitzerlandJobsParser(
        transport=catalog_handler([listing(101, country="de")], [detail(101)])
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_bosch_rejects_mismatched_listing_and_detail_ids() -> None:
    parser = BoschSwitzerlandJobsParser(
        max_catalog_passes=1,
        transport=catalog_handler([listing(101)], [detail(102)]),
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 1"):
        parser.search(LinkedInSearchRequest())


def test_bosch_rejects_invalid_smartrecruiters_application_url() -> None:
    parser = BoschSwitzerlandJobsParser(
        transport=catalog_handler(
            [listing(101)],
            [detail(101, apply_host="example.com")],
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="SmartRecruiters URL"):
        parser.search(LinkedInSearchRequest())


def test_bosch_accepts_verified_empty_catalog_without_detail_request() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.host == "jobs.bosch.com":
            return httpx.Response(200, text=config_html())
        return httpx.Response(200, json=listing_payload([], total=0))

    result = BoschSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 verified Bosch Switzerland vacancies from 0 CaaS country "
        "records across 1 API page requests in 1 catalog pass(es)"
    )
    assert len(requested_paths) == 2


def test_bosch_enforces_catalog_page_limit() -> None:
    records = [listing(job_id) for job_id in (101, 102, 103)]
    parser = BoschSwitzerlandJobsParser(
        page_size=2,
        max_pages=1,
        transport=catalog_handler(records, [detail(101), detail(102), detail(103)]),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_bosch_rejects_base_url_without_switzerland_scope() -> None:
    parser = BoschSwitzerlandJobsParser(
        base_url="https://jobs.bosch.com/en/?pages=1&country=de#",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(DirectCompanyRequestError, match="lost its Switzerland"):
        parser.search(LinkedInSearchRequest())


def test_bosch_rejects_incomplete_api_configuration() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, text=config_html(api_key="missing"))
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected jobs API"):
        BoschSwitzerlandJobsParser(transport=transport).search(LinkedInSearchRequest())


def test_bosch_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bosch_switzerland"]
    assert isinstance(parser, BoschSwitzerlandJobsParser)
    assert parser.base_url == settings.bosch_switzerland_jobs_base_url
    assert parser.page_size == settings.bosch_switzerland_jobs_page_size
    assert parser.max_pages == settings.bosch_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.bosch_switzerland_jobs_max_catalog_passes
    assert parser.page_workers == settings.bosch_switzerland_jobs_page_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bosch Switzerland", "filters": {}},
            "sources": ["bosch_switzerland", "bosch_switzerland"],
        }
    )
    assert request.sources == ["bosch_switzerland"]


def test_bosch_jobs_render_as_direct_company_imports() -> None:
    raw_listing = listing(101)
    raw_listing["detail"] = {
        **detail(101),
        "id": "REF101G",
        "public_url": ("https://jobs.bosch.com/en/job/REF101G-automation-engineer-w-m-div-ref101g"),
    }
    job = BoschSwitzerlandJobsParser().normalize_job(raw_listing)
    stored = parsed_job_to_stored_job(
        job,
        job_id="bosch_switzerland-REF101G",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bosch Switzerland import"
    assert stored["id"] == "bosch_switzerland-REF101G"
