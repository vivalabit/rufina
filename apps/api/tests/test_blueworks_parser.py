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
from app.services.parsers.companies.blueworks import (
    BLUEWORKS_API_URL,
    BLUEWORKS_CAREERS_URL,
    BlueworksJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

COMPANY_ID = 145851
JOBS = tuple(
    {
        "id": 15934805 + index,
        "idParam": f"1658264{index}-sap-consultant-{index}",
        "title": f"SAP Consultant {index}",
        "createdAt": f"2026-08-{10 + index:02d}T12:00:00.000Z",
        "companyId": COMPANY_ID,
        "workplaceType": "HYBRID" if index == 0 else "ONSITE",
        "city": {
            "cityName": "Zug",
            "countryName": "Switzerland",
        },
        "country": {"iso3166": "CH", "name": "Switzerland"},
        "employmentType": {"name": "Employee"},
        "category": {"name": "Consulting, Engineering"},
        "settings": {"showSalary": False},
    }
    for index in range(6)
)


def company_payload() -> dict[str, object]:
    company = {
        "id": COMPANY_ID,
        "name": "blueworks AG",
        "domain": "blue",
        "url": "https://blue.works",
        "isPublic": True,
    }
    return {
        "props": {"pageProps": {"initialState": {"company": company}}},
        "page": "/companies/[companySlug]",
        "query": {"companySlug": "blue"},
    }


def company_html() -> str:
    organization = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "blueworks AG",
        "url": BLUEWORKS_CAREERS_URL,
        "sameAs": "https://blue.works",
    }
    return f"""
    <html lang="en"><head>
      <title>Jobs at blueworks AG | JOIN</title>
      <link rel="canonical" href="{BLUEWORKS_CAREERS_URL}">
      <meta property="og:url" content="{BLUEWORKS_CAREERS_URL}">
      <script type="application/ld+json">{json.dumps(organization)}</script>
    </head><body>
      <h1>blueworks AG</h1>
      <script id="__NEXT_DATA__" type="application/json">
        {json.dumps(company_payload())}
      </script>
    </body></html>
    """


def catalog_payload(page: int) -> dict[str, object]:
    start = (page - 1) * 5
    items = JOBS[start : start + 5]
    return {
        "items": items,
        "aggregations": [],
        "pagination": {
            "rowCount": len(JOBS),
            "pageCount": 2,
            "page": page,
            "pageSize": len(items),
        },
    }


def detail_html(job: dict[str, object]) -> str:
    canonical_url = f"{BLUEWORKS_CAREERS_URL}/{job['idParam']}"
    title = str(job["title"])
    detail = {
        **job,
        "company": {
            "id": COMPANY_ID,
            "name": "blueworks AG",
            "domain": "blue",
        },
        "status": "ONLINE",
        "description": (
            "Build modern SAP transformation solutions.\n\n"
            "## Tasks\n\n* Advise customers end to end."
        ),
        "employmentType": {
            "name": "Angestellte/r",
            "googleType": "FULL_TIME",
        },
    }
    next_data = {
        "props": {"pageProps": {"initialState": {"job": detail}}},
        "page": "/companies/[companySlug]/[id]",
        "query": {"companySlug": "blue", "id": job["idParam"]},
    }
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "datePosted": job["createdAt"],
        "description": "<p>Build modern SAP transformation solutions.</p>",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "blueworks AG",
        },
        "title": title,
        "url": canonical_url,
    }
    return f"""
    <html lang="de"><head>
      <title>{title}</title>
      <link rel="canonical" href="{canonical_url}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <h1>{title}</h1>
      <script id="__NEXT_DATA__" type="application/json">
        {json.dumps(next_data)}
      </script>
    </body></html>
    """


def parser_with_catalog(
    *,
    detail_status: int = 200,
    max_pages: int = 100,
) -> tuple[BlueworksJobsParser, list[int]]:
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/companies/blue":
            return httpx.Response(200, text=company_html(), request=request)
        if request.url.path == "/api/public/companies/145851/jobs":
            page = int(request.url.params["page"])
            requested_pages.append(page)
            return httpx.Response(200, json=catalog_payload(page), request=request)
        stable_job = next(
            (job for job in JOBS if request.url.path == f"/companies/blue/{job['id']}"),
            None,
        )
        if stable_job is not None:
            if detail_status != 200:
                return httpx.Response(detail_status, request=request)
            return httpx.Response(
                301,
                headers={"Location": (f"{BLUEWORKS_CAREERS_URL}/{stable_job['idParam']}")},
                request=request,
            )
        current_job = next(
            (job for job in JOBS if request.url.path == f"/companies/blue/{job['idParam']}"),
            None,
        )
        if current_job is not None:
            return httpx.Response(
                200,
                text=detail_html(current_job),
                request=request,
            )
        return httpx.Response(404, request=request)

    parser = BlueworksJobsParser(
        base_url=BLUEWORKS_CAREERS_URL,
        api_url=BLUEWORKS_API_URL,
        max_pages=max_pages,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )
    return parser, requested_pages


def test_blueworks_collects_every_page_and_enriches_details() -> None:
    parser, requested_pages = parser_with_catalog()

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert requested_pages == [1, 2]
    assert result.status == "completed"
    assert result.message == ("Scanned 6 blueworks vacancies from the official JOIN catalog")
    assert len(result.jobs) == 6

    first = result.jobs[0]
    assert first.source == "blueworks"
    assert first.title == "SAP Consultant 0"
    assert first.company == "blueworks AG"
    assert first.location == "Zug, Switzerland (Hybrid)"
    assert first.url == f"{BLUEWORKS_CAREERS_URL}/15934805"
    assert first.apply_url == f"{BLUEWORKS_CAREERS_URL}/16582640-sap-consultant-0"
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "Full-time"
    assert "Advise customers end to end" in (first.description or "")
    assert result.jobs[-1].raw["page"] == 2


def test_blueworks_preserves_listing_records_when_details_fail() -> None:
    parser, _ = parser_with_catalog(detail_status=503)

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 6
    assert result.jobs[0].location == "Zug, Switzerland (Hybrid)"
    assert result.jobs[0].posted_at == "2026-08-10"
    assert result.jobs[0].employment_type == "Employee"
    assert result.jobs[0].description is None
    assert result.jobs[0].apply_url == (f"{BLUEWORKS_CAREERS_URL}/16582640-sap-consultant-0")
    assert all("503 Service Unavailable" in job.raw["detail_error"] for job in result.jobs)


def test_blueworks_rejects_wrong_identity_and_malformed_api() -> None:
    wrong_identity = company_html().replace("blueworks AG", "Lookalike AG")
    parser = BlueworksJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=wrong_identity, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/companies/blue":
            return httpx.Response(200, text=company_html(), request=request)
        return httpx.Response(200, json={"items": "broken"}, request=request)

    parser = BlueworksJobsParser(transport=httpx.MockTransport(malformed_handler))
    with pytest.raises(DirectCompanyRequestError, match="invalid payload"):
        parser.search(LinkedInSearchRequest())


def test_blueworks_enforces_page_limit_and_wraps_http_failures() -> None:
    parser, requested_pages = parser_with_catalog(max_pages=1)
    with pytest.raises(DirectCompanyRequestError, match="configured page limit"):
        parser.search(LinkedInSearchRequest())
    assert requested_pages == [1]

    parser = BlueworksJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_blueworks_is_registered_and_stored_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["blueworks"]
    assert isinstance(parser, BlueworksJobsParser)
    assert parser.base_url == settings.blueworks_jobs_base_url
    assert parser.api_url == settings.blueworks_jobs_api_url
    assert parser.max_pages == settings.blueworks_jobs_max_pages
    assert parser.detail_workers == settings.blueworks_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "blueworks", "filters": {}},
            "sources": ["blueworks", "blueworks"],
        }
    )
    assert request.sources == ["blueworks"]

    job = normalize_job(
        {
            **JOBS[0],
            "stable_url": f"{BLUEWORKS_CAREERS_URL}/{JOBS[0]['id']}",
            "current_url": f"{BLUEWORKS_CAREERS_URL}/{JOBS[0]['idParam']}",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="blueworks-https-join-com-companies-blue-15934805",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "blueworks AG import"
    assert stored["id"] == "blueworks-https-join-com-companies-blue-15934805"
