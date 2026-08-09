from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.baloise import BaloiseJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

JOB_ID_1 = "76a59d77-7553-4683-8e4c-961a2bc0e56f"
JOB_ID_2 = "7823517b-fcc0-4ef0-9244-e394fe41270a"


class JsonResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def json(self) -> Any:
        return self.payload

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"JSON response does not support CSS: {selector}")


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def json(self) -> Any:
        raise AssertionError("HTML response is not JSON")

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)


class TrailingSchemaResponse:
    """Match Helvetia's JSON-LD emitted after the closing HTML element."""

    def __init__(self, page_html: str) -> None:
        self.body = page_html.encode()
        document_html = page_html.split("<script", maxsplit=1)[0]
        self.selector = Selector(document_html)

    def json(self) -> Any:
        raise AssertionError("HTML response is not JSON")

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)


def catalog_item(
    job_id: str,
    *,
    title: str = "Security Engineer (w/m/d)",
    location: str = "Schweiz, Basel",
) -> dict[str, Any]:
    return {
        "coords": {"lat": 47.5596, "lng": 7.5886},
        "title": title,
        "subTitle": location,
        "href": f"https://jobs.helvetia.com/offene-stellen/security-engineer/{job_id}",
        "buttonText": "Mehr erfahren @Helvetia",
        "batch": "NEU",
        "zip": "4001",
    }


def catalog_payload(
    items: list[dict[str, Any]],
    *,
    total: int | None = None,
) -> dict[str, Any]:
    declared_total = len(items) if total is None else total
    split_at = max(1, len(items) // 2)
    pages = [items[:split_at]]
    if items[split_at:]:
        pages.append(items[split_at:])
    return {
        "text": [f"{declared_total} Job(s)"],
        "results": [{"items": page} for page in pages],
    }


def detail_html(
    job_id: str,
    *,
    title: str = "Security Engineer (w/m/d)",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-08-07",
        "validThrough": "2036-08-03",
        "employmentType": "FULL_TIME",
        "industry": "Versicherungen",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Helvetia Versicherungen",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "Schweiz",
                "addressLocality": "Basel",
                "postalCode": "4001",
            },
        },
        "description": (
            "<h3>Gestalte die gemeinsame Zukunft.</h3>"
            "<ul><li>Schütze unsere Plattformen.</li><li>Führe Reviews durch.</li></ul>"
        ),
    }
    return f"""
    <html><body>
      <a class="header-apply-button"
         href="https://ohws.prospective.ch/public/v1/redirect/{job_id}/ats/">
        Jetzt bewerben
      </a>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_baloise_scans_full_swiss_catalog_and_enriches_details() -> None:
    calls: list[str] = []
    payload = catalog_payload(
        [
            catalog_item(JOB_ID_1),
            catalog_item(
                JOB_ID_2,
                title="Cloud Engineer (w/m/d)",
                location="Schweiz, Zürich",
            ),
        ]
    )

    def fetch_page(url: str) -> JsonResponse | HtmlResponse:
        calls.append(url)
        if "jobSearchWidget.json" in url:
            return JsonResponse(payload)
        job_id = url.rstrip("/").rsplit("/", maxsplit=1)[-1]
        return HtmlResponse(detail_html(job_id))

    parser = BaloiseJobsParser(
        base_url="https://www.baloise.test/de/CH/jobs.html",
        catalog_url="https://www.baloise.test/jobSearchWidget.json",
        max_jobs=500,
        detail_workers=2,
        fetch_page=fetch_page,
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.search_url == "https://www.baloise.test/de/CH/jobs.html"
    assert result.message == ("Scanned 2 Baloise vacancies from 2 Swiss catalog records")
    assert len(result.jobs) == 2
    catalog_query = parse_qs(urlsplit(calls[0]).query, keep_blank_values=True)
    assert catalog_query == {
        "displayLimit": ["500"],
        "editMode": ["false"],
        "query-str": [""],
        "search-widget-radius-select-country": ["CHE"],
    }

    first = result.jobs[0]
    assert first.source == "baloise"
    assert first.title == "Security Engineer (w/m/d)"
    assert first.company == "Helvetia Versicherungen"
    assert first.location == "Schweiz, Basel"
    assert first.url == (f"https://jobs.helvetia.com/offene-stellen/security-engineer/{JOB_ID_1}")
    assert first.apply_url == (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_ID_1}/ats/")
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full time"
    assert first.description and "- Schütze unsere Plattformen." in first.description
    assert first.raw["catalog_page"] == 1
    assert first.raw["total_available"] == 2
    assert first.raw["detail"]["industry"] == "Versicherungen"


def test_baloise_preserves_listing_when_detail_request_fails() -> None:
    def fetch_page(url: str) -> JsonResponse:
        if "jobSearchWidget.json" in url:
            return JsonResponse(catalog_payload([catalog_item(JOB_ID_1)]))
        raise RuntimeError("detail temporarily unavailable")

    parser = BaloiseJobsParser(
        catalog_url="https://www.baloise.test/jobSearchWidget.json",
        fetch_page=fetch_page,
    )
    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Security Engineer (w/m/d)"
    assert job.company == "Baloise"
    assert job.location == "Schweiz, Basel"
    assert job.apply_url == job.url
    assert job.description is None
    assert "temporarily unavailable" in str(job.raw["detail_error"])


def test_baloise_reads_jobposting_emitted_after_closing_html() -> None:
    page_html = detail_html(JOB_ID_1)
    apply_markup, schema_markup = page_html.split("<script", maxsplit=1)
    trailing_page = f"{apply_markup}</html><script{schema_markup}"

    def fetch_page(url: str) -> JsonResponse | TrailingSchemaResponse:
        if "jobSearchWidget.json" in url:
            return JsonResponse(catalog_payload([catalog_item(JOB_ID_1)]))
        return TrailingSchemaResponse(trailing_page)

    job = BaloiseJobsParser(fetch_page=fetch_page).search(LinkedInSearchRequest()).jobs[0]

    assert job.company == "Helvetia Versicherungen"
    assert job.description and "Gestalte die gemeinsame Zukunft" in job.description
    assert job.apply_url and "prospective.ch" in job.apply_url


def test_baloise_rejects_non_swiss_catalog_result() -> None:
    parser = BaloiseJobsParser(
        fetch_page=lambda _: JsonResponse(
            catalog_payload([catalog_item(JOB_ID_1, location="Deutschland, Hamburg")])
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_baloise_rejects_incomplete_catalog_contract() -> None:
    parser = BaloiseJobsParser(
        fetch_page=lambda _: JsonResponse(catalog_payload([catalog_item(JOB_ID_1)], total=2))
    )

    with pytest.raises(DirectCompanyRequestError, match="returned 1 vacancies"):
        parser.search(LinkedInSearchRequest())


def test_baloise_enforces_catalog_limit_before_detail_requests() -> None:
    parser = BaloiseJobsParser(
        max_jobs=1,
        fetch_page=lambda _: JsonResponse(
            catalog_payload([catalog_item(JOB_ID_1), catalog_item(JOB_ID_2)])
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_baloise_caps_detail_concurrency_for_scrapling_transport() -> None:
    assert BaloiseJobsParser(detail_workers=20).detail_workers == 8


def test_baloise_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["baloise"]
    assert isinstance(parser, BaloiseJobsParser)
    assert parser.base_url == settings.baloise_jobs_base_url
    assert parser.catalog_url == settings.baloise_jobs_catalog_url
    assert parser.max_jobs == settings.baloise_jobs_max_jobs
    assert parser.detail_workers == settings.baloise_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Baloise", "filters": {}},
            "sources": ["baloise", "baloise"],
        }
    )
    assert request.sources == ["baloise"]


def test_baloise_jobs_render_as_direct_company_imports() -> None:
    parser = BaloiseJobsParser(fetch_page=lambda _: JsonResponse({}))
    job = parser.normalize_job(
        {
            "id": JOB_ID_1,
            "title": "Security Engineer",
            "location": "Schweiz, Basel",
            "url": (f"https://jobs.helvetia.com/offene-stellen/security-engineer/{JOB_ID_1}"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"baloise-{JOB_ID_1}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Baloise import"
    assert stored["id"] == f"baloise-{JOB_ID_1}"
