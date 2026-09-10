from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.helsana import HelsanaJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.helsana.ch/de/helsana-gruppe/jobs/stellenangebote.html"
CATALOG_URL = "https://jobs.helsana.ch/?lang=de"


def vacancy_record(index: int) -> dict[str, str]:
    job_id = f"{index + 1:08x}-d82d-4393-9412-{index + 100:012x}"
    return {
        "id": job_id,
        "slug": f"platform-engineer-{index}",
        "title": f"Platform Engineer {index} (a) 80-100%",
        "location": "Zürich & Homeoffice",
        "posted_at": f"2026-08-{index + 10:02d}",
    }


def job_url(record: dict[str, str]) -> str:
    return f"https://jobs.helsana.ch/offene-stellen/{record['slug']}/{record['id']}"


def parent_html(
    *,
    title: str = "Offene Stellen - Helsana",
    widget_url: str = CATALOG_URL,
) -> str:
    header = html.escape(
        json.dumps(
            {
                "headerBar": {
                    "logo": {
                        "src": "/content/dam/system/helsana/resources/helsana-logo.svg"
                    }
                }
            }
        ),
        quote=True,
    )
    return f"""
    <html lang="de"><head><title>{title}</title>
      <link rel="canonical" href="{BASE_URL}">
      <meta property="og:url" content="{BASE_URL}">
    </head><body><detail-page header="{header}">
      <h1 class="h1">Offene Stellen</h1>
      <hls-video src="{widget_url}"></hls-video>
    </detail-page></body></html>
    """


def listing_html(
    records: list[dict[str, str]],
    *,
    offset: int,
    total: int,
    limit: int = 12,
    language: str = "de",
) -> str:
    cards = "".join(
        f"""
        <div class="job" data-filter-10="1202317">
          <a href="{job_url(record)}" title="{html.escape(record['title'])}"
             target="_blank"><h4>{html.escape(record['title'])}</h4>
            <p class="city">{html.escape(record['location'])}</p>
          </a><div class="job-favorit"></div>
        </div>
        """
        for record in records
    )
    pagination = (
        ""
        if total == 0
        else (
            '<div class="paging"><a class="page paging active" '
            f'title="Seite {offset // limit + 1}">{offset // limit + 1}</a></div>'
        )
    )
    return f"""
    <html lang="{language}"><head><title>Helsana: Career center</title>
      <link href="/careercenter/1002787/assets/css/helsana.css?v=2"
            rel="stylesheet">
    </head><body><form id="careercenter-form" method="post">
      <input name="offset" value="{offset}"><input name="limit" value="{limit}">
      <input name="lang" value="de">
    </form><div id="jobs"><strong>Alle Jobs
      (<span class="nrOfJobs">{total}</span>)</strong>{cards}</div>{pagination}
    </body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    company: str = "Helsana Versicherungen AG",
    country: str = "Schweiz",
    apply_id: str | None = None,
    canonical_path: str = "offene-stellen",
) -> str:
    description = (
        "Du entwickelst zuverlässige Plattformen für unsere Kundinnen und Kunden, "
        "übernimmst Verantwortung von der Konzeption bis zum Betrieb und arbeitest "
        "eng mit unseren Produkt-, Infrastruktur- und Security-Teams zusammen."
    )
    posting = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": record["title"],
        "description": f"<h3>Deine Aufgabe</h3><p>{description}</p>",
        "datePosted": record["posted_at"],
        "validThrough": "2026-09-30",
        "employmentType": "PART_TIME",
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": "Zürich",
            },
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "CHF",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": "100000",
                "maxValue": "125000",
                "unitText": ["JAHR"],
            },
        },
    }
    application_id = apply_id or record["id"]
    apply_url = (
        "https://ohws.prospective.ch/public/v1/redirect/"
        f"{application_id}/ats/"
    )
    canonical_url = (
        f"https://jobs.helsana.ch/{canonical_path}/{record['slug']}/{record['id']}"
    )
    return f"""
    <html lang="de"><head><title>Helsana: {html.escape(record['title'])}</title>
      <link rel="canonical" href="{canonical_url}">
      <meta property="og:site_name" content="Helsana">
    </head><body><section class="title">
      <h1 id="addTooltip">{html.escape(record['title'])}</h1>
      <h4>{html.escape(record['location'])}</h4>
    </section><footer><a class="button apply" href="{apply_url}">
      Jetzt bewerben</a></footer></body></html>
    <script type="application/ld+json">{json.dumps(posting)}</script>
    """


def request_offset(request: httpx.Request) -> int:
    body = parse_qs(request.content.decode())
    assert body["limit"] == ["12"]
    assert body["lang"] == ["de"]
    return int(body["offset"][0])


def test_helsana_scans_full_catalog_and_enriches_every_record() -> None:
    records = [vacancy_record(index) for index in range(13)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "www.helsana.ch":
            return httpx.Response(200, text=parent_html(), request=request)
        if request.method == "POST":
            offset = request_offset(request)
            page_records = records[:12] if offset == 0 else records[12:]
            return httpx.Response(
                200,
                text=listing_html(
                    page_records,
                    offset=offset,
                    total=13,
                ),
                request=request,
            )
        record = next(item for item in records if request.url.path == httpx.URL(job_url(item)).path)
        detail = (
            detail_html(
                record,
                country="Suisse",
                canonical_path="emplois-vacantes",
            )
            if record is records[1]
            else detail_html(record)
        )
        return httpx.Response(200, text=detail, request=request)

    result = HelsanaJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 16
    assert result.message == (
        "Scanned 13 Helsana vacancies from 13 catalog records across 2 page requests"
    )
    assert len(result.jobs) == 13
    job = result.jobs[0]
    assert job.source == "helsana"
    assert job.title == records[0]["title"]
    assert job.company == "Helsana Versicherungen AG"
    assert job.location == "Zürich & Homeoffice"
    assert job.url == job_url(records[0])
    assert job.apply_url.endswith(f"/{records[0]['id']}/ats/")
    assert job.posted_at == "2026-08-10"
    assert job.employment_type == "80–100%"
    assert job.description and job.description.startswith("Deine Aufgabe")
    assert job.salary == "100000–125000 CHF/JAHR"
    assert job.salary_min == 100000
    assert job.salary_max == 125000
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 13
    assert job.raw["detail"]["schema_employment_type"] == "PART_TIME"


def test_helsana_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [vacancy_record(index) for index in range(13)]
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.host == "www.helsana.ch":
            return httpx.Response(200, text=parent_html(), request=request)
        if request.method == "POST":
            offset = request_offset(request)
            if offset == 0:
                first_page_calls += 1
                page = records[:12] if first_page_calls == 1 else records[1:]
            else:
                page = [records[0]]
            return httpx.Response(
                200,
                text=listing_html(page, offset=offset, total=13),
                request=request,
            )
        record = next(item for item in records if request.url.path == httpx.URL(job_url(item)).path)
        return httpx.Response(200, text=detail_html(record), request=request)

    result = HelsanaJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 13
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_helsana_preserves_verified_listing_when_detail_fails() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.helsana.ch":
            return httpx.Response(200, text=parent_html(), request=request)
        if request.method == "POST":
            return httpx.Response(
                200,
                text=listing_html([record], offset=0, total=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        HelsanaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == record["title"]
    assert job.location == record["location"]
    assert job.apply_url == job_url(record)
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("parent", "message"),
    [
        (parent_html(title="Generic careers"), "unexpected identity"),
        (parent_html(widget_url="https://example.com/jobs"), "official Career Center"),
    ],
)
def test_helsana_rejects_untrusted_parent_page(parent: str, message: str) -> None:
    parser = HelsanaJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=parent, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (listing_html([], offset=0, total=0, language="en"), "unexpected identity"),
        (listing_html([], offset=0, total=1), "incomplete page"),
        (
            listing_html(
                [vacancy_record(0), vacancy_record(0)],
                offset=0,
                total=2,
            ),
            "duplicate vacancy",
        ),
    ],
)
def test_helsana_rejects_invalid_catalogs(catalog: str, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = parent_html() if request.url.host == "www.helsana.ch" else catalog
        return httpx.Response(200, text=content, request=request)

    with pytest.raises(DirectCompanyRequestError, match=message):
        HelsanaJobsParser(transport=httpx.MockTransport(handler)).search(
            LinkedInSearchRequest()
        )


def test_helsana_rejects_invalid_detail_but_keeps_listing() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.helsana.ch":
            content = parent_html()
        elif request.method == "POST":
            content = listing_html([record], offset=0, total=1)
        else:
            content = detail_html(record, company="Other Company")
        return httpx.Response(200, text=content, request=request)

    job = (
        HelsanaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description is None
    assert "invalid JobPosting metadata" in str(job.raw["detail_error"])


def test_helsana_accepts_empty_catalog_and_enforces_page_limit() -> None:
    def response_for(catalog: str):
        def handler(request: httpx.Request) -> httpx.Response:
            content = parent_html() if request.url.host == "www.helsana.ch" else catalog
            return httpx.Response(200, text=content, request=request)

        return httpx.MockTransport(handler)

    empty = HelsanaJobsParser(
        transport=response_for(listing_html([], offset=0, total=0))
    ).search(LinkedInSearchRequest())
    assert empty.jobs == []
    assert empty.message.endswith("across 1 page request")

    too_large = HelsanaJobsParser(
        max_pages=1,
        transport=response_for(
            listing_html(
                [vacancy_record(index) for index in range(12)],
                offset=0,
                total=13,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())


def test_helsana_wraps_http_errors() -> None:
    parser = HelsanaJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_helsana_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["helsana"]
    assert isinstance(parser, HelsanaJobsParser)
    assert parser.base_url == settings.helsana_jobs_base_url
    assert parser.career_center_url == settings.helsana_jobs_career_center_url
    assert parser.max_pages == settings.helsana_jobs_max_pages
    assert parser.max_catalog_passes == settings.helsana_jobs_max_catalog_passes
    assert parser.detail_workers == settings.helsana_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Helsana", "filters": {}},
            "sources": ["helsana", "helsana"],
        }
    )
    assert request.sources == ["helsana"]


def test_helsana_jobs_render_as_direct_company_imports() -> None:
    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["id"],
                "title": record["title"],
                "location": record["location"],
                "employment_type": "80–100%",
                "url": job_url(record),
            }
        ),
        job_id=f"helsana-{record['id']}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Helsana import"
    assert stored["company"] == "Helsana Versicherungen AG"
    assert stored["id"] == f"helsana-{record['id']}"


def test_helsana_retries_failed_details_before_partial_validation(monkeypatch) -> None:
    from app.services.parser_validation import validate_parser_result
    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", lambda _: None)
    records = [vacancy_record(0), vacancy_record(1)]
    calls: list[str] = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "www.helsana.ch":
            return httpx.Response(200, text=parent_html())
        if request.method == "POST":
            return httpx.Response(200, text=listing_html(records, offset=0, total=2))
        record = next(record for record in records if job_url(record) == str(request.url))
        if record == records[1] and calls.count(str(request.url)) == 1:
            return httpx.Response(503)
        return httpx.Response(200, text=detail_html(record))
    result = HelsanaJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())
    assert validate_parser_result(result)[1] is None
    assert all(job.description and "detail_error" not in job.raw for job in result.jobs)
    assert calls.count(job_url(records[0])) == 1
    assert calls.count(job_url(records[1])) == 2
    assert len(calls) == 5  # Corporate page, catalog, two details and one retry.
