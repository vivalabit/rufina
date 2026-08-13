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
from app.services.parsers.companies.datwyler_it_infra import (
    DatwylerItInfraJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = (
    "https://careers.datwyler.test/search/?locale=de_DE&searchResultView=LIST&"
    "facetFilters=%7B%22jobLocationCountry%22%3A%5B%22Schweiz%22%5D%7D&"
    "pageNumber=0"
)
API_URL = "https://careers.datwyler.test/services/recruiting/v1/jobs"


def api_record(
    job_id: int,
    *,
    title: str | None = None,
    country: str = "Schweiz",
    location: str = "Villmergen, CHE, 5612<br/>",
    workplace_type: str = "Hybrid",
    posted_at: str = "10.07.26",
) -> dict[str, object]:
    return {
        "response": {
            "id": str(job_id),
            "unifiedStandardTitle": title or f"Network Engineer {job_id}",
            "unifiedUrlTitle": f"Network-Engineer-{job_id}",
            "unifiedStandardStart": posted_at,
            "jobLocationCountry": [country],
            "jobLocationShort": [location],
            "supportedLocales": ["de_DE"],
            "workplacetype": [workplace_type],
        }
    }


def api_payload(records: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {"jobSearchResult": records, "totalJobs": total}


def detail_html(
    job_id: int,
    *,
    title: str | None = None,
    location: str = "Villmergen",
    workplace_type: str = "Hybrid",
    apply_job_id: int | None = None,
    canonical_url: str | None = None,
) -> str:
    job_title = title or f"Network Engineer {job_id}"
    canonical = canonical_url or (
        f"https://careers.datwyler.test/job/Network-Engineer-{job_id}/{job_id}-de_DE/"
    )
    application_id = apply_job_id or job_id
    return f"""
    <html>
      <head><link rel="canonical" href="{canonical}"></head>
      <body>
        <div class="jobDisplayShell" itemscope
             itemtype="http://schema.org/JobPosting">
          <span itemprop="title">{job_title}</span>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Stellenstandort:&nbsp;</span>
            <span class="rtltextaligneligible">{location}</span>
          </div>
          <div class="joblayouttoken">
            <span class="joblayouttoken-label">Arbeitsmodell:&nbsp;</span>
            <span class="rtltextaligneligible">{workplace_type}</span>
          </div>
          <span itemprop="description">
            <p><strong>Damit verbringst du deine Zeit</strong></p>
            <p>• Du planst zuverlässige Netzwerklösungen.</p>
            <p>• Du arbeitest eng mit dem Engineering-Team zusammen.</p>
          </span>
          <a class="dialogApplyBtn"
             href="/talentcommunity/apply/{application_id}/?locale=de_DE">
            Jetzt bewerben
          </a>
        </div>
      </body>
    </html>
    """


def test_datwyler_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/services/recruiting/v1/jobs":
            body = json.loads(request.content)
            page_number = body["pageNumber"]
            records = (
                [api_record(432), api_record(436)]
                if page_number == 0
                else [
                    api_record(
                        437,
                        title="Treasury Controller 60% (all genders)",
                        location="Altdorf, CHE, 6460<br/>",
                        posted_at="22.07.26",
                    )
                ]
            )
            return httpx.Response(200, json=api_payload(records, total=3))
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
        return httpx.Response(
            200,
            text=detail_html(
                job_id,
                title=(
                    "Treasury Controller 60% (all genders)"
                    if job_id == 437
                    else f"Network Engineer {job_id}"
                ),
                location="Altdorf" if job_id == 437 else "Villmergen",
            ),
            request=request,
        )

    result = DatwylerItInfraJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Dätwyler IT Infra Switzerland vacancies from 3 catalog "
        "records across 2 page requests"
    )
    assert len(result.jobs) == 3
    listing_requests = [
        request for request in requests if request.url.path == "/services/recruiting/v1/jobs"
    ]
    assert len(listing_requests) == 2
    first_payload = json.loads(listing_requests[0].content)
    assert first_payload == {
        "keywords": "",
        "locale": "de_DE",
        "location": "",
        "pageNumber": 0,
        "sortBy": "recent",
        "facetFilters": {"jobLocationCountry": ["Schweiz"]},
    }
    assert json.loads(listing_requests[1].content)["pageNumber"] == 1

    job = result.jobs[0]
    assert job.source == "datwyler_it_infra"
    assert job.title == "Network Engineer 432"
    assert job.company == "Dätwyler IT Infra"
    assert job.location == "Villmergen, CHE, 5612"
    assert job.url == ("https://careers.datwyler.test/job/Network-Engineer-432/432-de_DE")
    assert job.apply_url == (
        "https://careers.datwyler.test/talentcommunity/apply/432/?locale=de_DE"
    )
    assert job.posted_at == "2026-07-10"
    assert job.employment_type is None
    assert job.description == (
        "Damit verbringst du deine Zeit\n"
        "- Du planst zuverlässige Netzwerklösungen.\n"
        "- Du arbeitest eng mit dem Engineering-Team zusammen."
    )
    assert job.raw["workplace_type"] == "Hybrid"
    assert job.raw["listing_pass"] == 1
    assert result.jobs[2].location == "Altdorf, CHE, 6460"


def test_datwyler_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/services/recruiting/v1/jobs":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1].split("-")[0])
            return httpx.Response(200, text=detail_html(job_id), request=request)
        page_number = json.loads(request.content)["pageNumber"]
        if page_number == 0:
            first_page_calls += 1
            records = [api_record(432), api_record(436)]
        else:
            records = [api_record(436 if first_page_calls == 1 else 437)]
        return httpx.Response(200, json=api_payload(records, total=3), request=request)

    result = DatwylerItInfraJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_datwyler_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/services/recruiting/v1/jobs":
            return httpx.Response(
                200,
                json=api_payload([api_record(432)], total=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        DatwylerItInfraJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Network Engineer 432"
    assert job.location == "Villmergen, CHE, 5612"
    assert job.apply_url == (
        "https://careers.datwyler.test/talentcommunity/apply/432/?locale=de_DE"
    )
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_datwyler_rejects_duplicate_or_non_swiss_catalog_records() -> None:
    def parser_for(records: list[dict[str, object]]) -> DatwylerItInfraJobsParser:
        return DatwylerItInfraJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=api_payload(records, total=len(records)),
                    request=request,
                )
            ),
        )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([api_record(432), api_record(432)]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parser_for([api_record(432, country="Deutschland", location="Berlin, DEU, 10115")]).search(
            LinkedInSearchRequest()
        )


def test_datwyler_rejects_malformed_catalog_and_mismatched_detail() -> None:
    parser = DatwylerItInfraJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"totalJobs": 0}, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        parser.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(432, apply_job_id=999),
            page_url="https://careers.datwyler.test/job/Network-Engineer-432/432-de_DE/",
            expected_url="https://careers.datwyler.test/job/Network-Engineer-432/432-de_DE",
            expected_job_id="432",
            expected_title="Network Engineer 432",
            expected_location="Villmergen, CHE, 5612",
            expected_workplace_type="Hybrid",
        )


def test_datwyler_enforces_catalog_page_limit() -> None:
    parser = DatwylerItInfraJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=api_payload([api_record(432), api_record(436)], total=3),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_datwyler_wraps_listing_request_failures() -> None:
    parser = DatwylerItInfraJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_datwyler_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["datwyler_it_infra"]
    assert isinstance(parser, DatwylerItInfraJobsParser)
    assert parser.base_url == settings.datwyler_it_infra_jobs_base_url
    assert parser.api_url == settings.datwyler_it_infra_jobs_api_url
    assert parser.max_pages == settings.datwyler_it_infra_jobs_max_pages
    assert parser.max_catalog_passes == settings.datwyler_it_infra_jobs_max_catalog_passes
    assert parser.detail_workers == settings.datwyler_it_infra_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Dätwyler IT Infra", "filters": {}},
            "sources": ["datwyler_it_infra", "datwyler_it_infra"],
        }
    )
    assert request.sources == ["datwyler_it_infra"]


def test_datwyler_jobs_render_as_direct_company_imports() -> None:
    job = DatwylerItInfraJobsParser().normalize_job(
        {
            "id": "432",
            "title": "Network Engineer",
            "location": "Villmergen, CHE, 5612",
            "posted_at": "2026-07-10",
            "workplace_type": "Hybrid",
            "url": ("https://careers.datwyler-itinfra.com/job/Network-Engineer/432-de_DE"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="datwyler_it_infra-432",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Dätwyler IT Infra import"
    assert stored["id"] == "datwyler_it_infra-432"
