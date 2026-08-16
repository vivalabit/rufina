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
from app.services.parsers.companies.eviden_switzerland import (
    EvidenSwitzerlandJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing(
    internal_id: int,
    posting_id: int,
    *,
    title: str | None = None,
    brand: str = "2",
    experience: str = "2",
    date: str = "Aug 14, 2026",
) -> dict[str, Any]:
    job_title = title or f"System Engineer {internal_id}"
    return {
        "id": str(internal_id),
        "title": job_title,
        "t": "",
        "date": date,
        "url": (
            f"https://jobs.atos.net/job/Zurich-System-Engineer-{internal_id}/"
            f"{posting_id}/?feedId=365901&utm_source=CareerSite"
        ),
        "exp": experience,
        "brand": brand,
    }


def catalog_html(
    records: list[dict[str, Any]],
    *,
    locations: dict[str, list[str]] | None = None,
    cities: dict[str, dict[str, str]] | None = None,
    declared_total: int | None = None,
    declared_pages: int | None = None,
) -> str:
    total = len(records) if declared_total is None else declared_total
    limit = 2
    pages = ((total + limit - 1) // limit) if declared_pages is None else declared_pages
    resolved_locations = locations or {record["id"]: ["84"] for record in records}
    resolved_cities = cities or {
        "84": {
            "city_id": "84",
            "city": "Zürich",
            "n": "ZURICH",
            "country_id": "CH",
            "country": "Switzerland",
            "region": "",
        }
    }
    payload = {
        "page": 1,
        "limit": limit,
        "total": total,
        "pages": pages,
        "order": "creation",
        "direction": "desc",
        "results": records,
        "support": {
            "loc": "{city}, {country}",
            "city": resolved_cities,
            "locations": resolved_locations,
            "exp": {
                "1": {"id": "1", "name": "Entry Level (1-3 years Experience)"},
                "2": {"id": "2", "name": "Experienced"},
            },
            "brand": {"2": {"id": "2", "name": "Eviden"}},
            "template": "<li>{title}</li>",
        },
    }
    return (
        "<html><body>"
        f'<div id="atosjobs_test" class="atosjobs" data-page="1" '
        f'data-pages="{pages}" data-paginate="1"></div>'
        f"<script>window['atosjobs_test']={json.dumps(payload)};</script>"
        "</body></html>"
    )


def detail_html(
    record: dict[str, Any],
    *,
    canonical_id: str | None = None,
    apply_id: str | None = None,
    location: str = "Zurich, CH",
    organization: str = "Atos",
) -> str:
    posting_id = record["url"].split("/")[-2]
    canonical_job_id = canonical_id or posting_id
    application_id = apply_id or posting_id
    title = record["title"]
    return f"""
    <html><head>
      <link rel="canonical"
        href="https://jobs.atos.net/job/Zurich-System-Engineer/{canonical_job_id}/">
    </head><body>
      <div class="jobDisplayShell" itemscope
           itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Fri Aug 14 00:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{organization}">
        <meta itemprop="streetAddress" content="{location}">
        <h1><span itemprop="title">{title}</span></h1>
        <span itemprop="description">
          <span class="jobdescription">
            <p>Build reliable systems.</p>
            <ul><li>Own delivery and automation.</li></ul>
          </span>
        </span>
        <span class="jobGeoLocation">{location}</span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{application_id}/?locale=en_US">Apply</a>
      </div>
    </body></html>
    """


def transport_for(
    records: list[dict[str, Any]],
    *,
    catalog: str | None = None,
    detail_kwargs: dict[str, Any] | None = None,
    requests: list[str] | None = None,
) -> httpx.MockTransport:
    html = catalog or catalog_html(records)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        if request.url.host == "eviden.com":
            assert request.url.params["country"] == "CH"
            return httpx.Response(200, text=html)
        posting_id = request.url.path.rstrip("/").split("/")[-1]
        record = next(item for item in records if posting_id in item["url"])
        return httpx.Response(200, text=detail_html(record, **(detail_kwargs or {})))

    return httpx.MockTransport(handler)


def test_eviden_filters_atomic_global_snapshot_and_enriches_all_swiss_jobs() -> None:
    records = [
        listing(101, 1401, title="SERVICE DELIVERY MANAGER"),
        listing(102, 1402),
        listing(103, 1403, date="May 12, 2026"),
    ]
    cities = {
        "84": {
            "city_id": "84",
            "city": "Zürich",
            "country_id": "CH",
            "country": "Switzerland",
            "region": "",
        },
        "77": {
            "city_id": "77",
            "city": "Gelsenkirchen",
            "country_id": "DE",
            "country": "Germany",
            "region": "",
        },
    }
    catalog = catalog_html(
        records,
        locations={"101": ["84"], "102": ["77"], "103": ["84", "77"]},
        cities=cities,
    )
    requested: list[str] = []
    parser = EvidenSwitzerlandJobsParser(
        detail_workers=2,
        transport=transport_for(records, catalog=catalog, requests=requested),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(requested) == 3
    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 verified Eviden Switzerland vacancies from 3 global Eviden "
        "records in one catalog snapshot with 2 detail requests"
    )
    first = result.jobs[0]
    assert first.source == "eviden_switzerland"
    assert first.title == "SERVICE DELIVERY MANAGER"
    assert first.company == "Eviden"
    assert first.location == "Zürich, Switzerland"
    assert first.url == "https://jobs.atos.net/job/Zurich-System-Engineer/1401/"
    assert first.apply_url == ("https://jobs.atos.net/talentcommunity/apply/1401/?locale=en_US")
    assert first.posted_at == "2026-08-14"
    assert first.seniority == "Experienced"
    assert first.description and "Own delivery and automation." in first.description
    assert first.raw["id"] == "101"
    assert result.jobs[1].location == "Zürich, Switzerland"
    assert result.jobs[1].posted_at == "2026-08-14"


@pytest.mark.parametrize(
    ("catalog", "error"),
    [
        (catalog_html([listing(101, 1401)], declared_total=2), "snapshot is incomplete"),
        (catalog_html([listing(101, 1401)], declared_pages=2), "page count"),
        (
            catalog_html([listing(101, 1401, brand="7")]),
            "support data is inconsistent",
        ),
    ],
)
def test_eviden_rejects_inconsistent_catalog(catalog: str, error: str) -> None:
    record = listing(101, 1401)
    parser = EvidenSwitzerlandJobsParser(transport=transport_for([record], catalog=catalog))

    with pytest.raises(DirectCompanyRequestError, match=error):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("detail_kwargs", "error"),
    [
        ({"canonical_id": "9999"}, "does not match"),
        ({"apply_id": "9999"}, "does not match"),
        ({"location": "Berlin, DE"}, "does not match"),
        ({"organization": "Example"}, "does not match"),
    ],
)
def test_eviden_rejects_mismatched_detail(detail_kwargs: dict[str, Any], error: str) -> None:
    record = listing(101, 1401)
    parser = EvidenSwitzerlandJobsParser(
        transport=transport_for([record], detail_kwargs=detail_kwargs)
    )

    with pytest.raises(DirectCompanyRequestError, match=error):
        parser.search(LinkedInSearchRequest())


def test_eviden_accepts_verified_empty_swiss_result_without_detail_requests() -> None:
    record = listing(101, 1401)
    cities = {
        "77": {
            "city_id": "77",
            "city": "Berlin",
            "country_id": "DE",
            "country": "Germany",
            "region": "",
        }
    }
    requested: list[str] = []
    catalog = catalog_html(records=[record], locations={"101": ["77"]}, cities=cities)

    result = EvidenSwitzerlandJobsParser(
        transport=transport_for([record], catalog=catalog, requests=requested)
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert len(requested) == 1
    assert result.message.endswith("with 0 detail requests")


def test_eviden_enforces_catalog_record_limit() -> None:
    records = [listing(101, 1401), listing(102, 1402)]
    parser = EvidenSwitzerlandJobsParser(
        max_catalog_records=1,
        transport=transport_for(records),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_eviden_rejects_base_url_without_ch_scope() -> None:
    parser = EvidenSwitzerlandJobsParser(
        base_url="https://eviden.com/careers/?country=DE",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(DirectCompanyRequestError, match="official CH careers filter"):
        parser.search(LinkedInSearchRequest())


def test_eviden_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["eviden_switzerland"]
    assert isinstance(parser, EvidenSwitzerlandJobsParser)
    assert parser.base_url == settings.eviden_switzerland_jobs_base_url
    assert parser.max_catalog_records == settings.eviden_switzerland_jobs_max_catalog_records
    assert parser.detail_workers == settings.eviden_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Eviden Switzerland", "filters": {}},
            "sources": ["eviden_switzerland", "eviden_switzerland"],
        }
    )
    assert request.sources == ["eviden_switzerland"]


def test_eviden_jobs_render_as_direct_company_imports() -> None:
    raw_record = {
        "id": "101",
        "title": "System Engineer",
        "posted_at": "2026-08-14",
        "location": "Zürich, Switzerland",
        "seniority": "Experienced",
        "detail": {
            "canonical_url": "https://jobs.atos.net/job/Zurich-System-Engineer/1401/",
            "apply_url": "https://jobs.atos.net/talentcommunity/apply/1401/?locale=en_US",
            "posted_at": "2026-08-14",
            "description": "Build reliable systems.",
        },
    }
    stored = parsed_job_to_stored_job(
        normalize_job(raw_record),
        job_id="eviden_switzerland-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Eviden Switzerland import"
    assert stored["id"] == "eviden_switzerland-101"
