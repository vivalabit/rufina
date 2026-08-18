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
from app.services.parsers.companies.lyreco_switzerland import (
    LyrecoSwitzerlandJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy_record(index: int) -> dict[str, str]:
    external_id = f"JR-{1_000_030_699 + index}"
    if index == 2:
        external_id += "-1"
    return {
        "internal_id": str(639 + index),
        "external_id": external_id,
        "slug": f"sales-manager-{index}-dietikon-zh",
        "title": f"Sales Manager {index} (m/w/d) 100%",
        "location": "Dietikon ZH",
        "family": "SA - Corporate",
        "employment_type": "Full time",
    }


def job_url(record: dict[str, str]) -> str:
    return f"https://www.lyreco.com/group/switzerland/de/jobs/{record['slug']}"


def vacancy_card(
    record: dict[str, str],
    *,
    location: str | None = None,
    host: str = "www.lyreco.com",
) -> str:
    return f"""
    <div class="job teaser views-row">
      <h2><a href="https://{host}/group/switzerland/de/jobs/{record["slug"]}">
        <div class="field field--name-title">{record["title"]}</div>
      </a></h2>
      <div class="job__info">
        <div class="job__info__location">{location or record["location"]}</div>
        <div class="job__info__family">{record["family"]}</div>
        <div class="job__info__time">{record["employment_type"]}</div>
      </div>
    </div>
    """


def facet(*, value: str, filter_value: str, count: int, active: bool = False) -> str:
    active_class = " is-active" if active else ""
    return f"""
    <a class="facet-item{active_class}"
       data-drupal-facet-item-value="{value}"
       data-drupal-facet-filter-value="{filter_value}"
       data-drupal-facet-item-count="{count}">
      <span class="facet-item__value">{value}</span>
      <span class="facet-item__count">({count})</span>
    </a>
    """


def listing_html(
    records: list[dict[str, str]],
    *,
    total: int,
    facet_total: int | None = None,
    title: str = "Stelle finden | Lyreco Schweiz",
    language: str = "de",
    location: str | None = None,
) -> str:
    facet_total = total if facet_total is None else facet_total
    cards = "".join(vacancy_card(record, location=location) for record in records)
    return f"""
    <html lang="{language}"><head><title>{title}</title>
      <link rel="canonical" href="https://www.lyreco.com/group/switzerland/en/jobs">
    </head><body><h1>Stelle finden</h1>
      <div class="jobs-total-results">{total} Resultate</div>
      {facet(value="dietikon zh", filter_value="job_location:dietikon zh", count=facet_total, active=True)}
      {facet(value="switzerland", filter_value="country:switzerland", count=facet_total)}
      {cards}
    </body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    title: str | None = None,
    country: str = "Switzerland",
    apply_host: str = "lyreco.wd3.myworkdayjobs.com",
) -> str:
    detail_title = title or record["title"]
    description = (
        "Du betreust internationale Firmenkunden und entwickelst nachhaltige Lösungen. "
        "Dabei koordinierst du interne Fachbereiche, erstellst Angebote und führst "
        "Verhandlungen. Gemeinsam mit dem Team sicherst du eine ausgezeichnete "
        "Customer Experience für unsere Kundinnen und Kunden in der Schweiz."
    )
    posting = {
        "@type": "JobPosting",
        "title": detail_title,
        "identifier": record["internal_id"],
        "employmentType": "Contractor",
        "datePosted": "2026-08-17",
        "hiringOrganization": {
            "@type": "Organization",
            "@id": "Lyreco",
            "name": "Lyreco",
            "url": "https://www.lyreco.com/group/switzerland/de",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": record["location"],
                "addressCountry": country,
            },
        },
        "description": description,
        "industry": record["family"],
    }
    apply_url = (
        f"https://{apply_host}/Lyreco_Careers/job/Dietikon-ZH/"
        f"Sales-Manager-{record['internal_id']}_{record['external_id']}/apply"
    )
    return f"""
    <html lang="de"><head><title>{detail_title} | Lyreco Schweiz</title>
      <link rel="canonical" href="https://www.lyreco.com/jobs/{record["slug"]}">
      <meta property="og:url" content="{job_url(record)}">
      <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": [posting]})}</script>
    </head><body><h1>{detail_title}</h1>
      <div class="job__field-primary-location">{record["location"]}</div>
      <div class="field--name-field-family">{record["family"]}</div>
      <div class="field--name-field-time-type">{record["employment_type"]}</div>
      <div class="field--name-field-description"><p>{description}</p></div>
      <div class="job__footer__content">
        <a class="btn btn-primary" href="{apply_url}">Bewerben</a>
        <a class="btn btn-primary" href="{apply_url}">Bewerben</a>
      </div>
    </body></html>
    """


def test_lyreco_scans_every_page_and_enriches_all_jobs() -> None:
    records = [vacancy_record(index) for index in range(12)]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/group/switzerland/de/jobs":
            page = int(request.url.params.get("page", "0"))
            page_records = records[:10] if page == 0 else records[10:]
            return httpx.Response(200, text=listing_html(page_records, total=12))
        record = next(item for item in records if request.url.path == httpx.URL(job_url(item)).path)
        return httpx.Response(200, text=detail_html(record))

    result = LyrecoSwitzerlandJobsParser(
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len([url for url in calls if "/group/switzerland/de/jobs?" in url]) == 2
    assert len([url for url in calls if "/group/switzerland/de/jobs/" in url]) == 12
    assert result.message == (
        "Scanned 12 Lyreco Switzerland vacancies from the complete Dietikon careers catalog"
    )
    assert len(result.jobs) == 12
    first = result.jobs[0]
    assert first.source == "lyreco_switzerland"
    assert first.company == "Lyreco Switzerland AG"
    assert first.location == "Dietikon ZH, Switzerland"
    assert first.url == job_url(records[0])
    assert first.apply_url and first.apply_url.endswith("_JR-1000030699/apply")
    assert first.posted_at == "2026-08-17"
    assert first.employment_type == "Full time"
    assert first.seniority is None
    assert first.description and first.description.startswith("Du betreust")
    assert first.raw["id"] == "JR-1000030699"
    assert first.raw["detail"]["internal_id"] == "639"
    assert first.raw["catalog_total"] == 12


def test_lyreco_preserves_verified_listing_when_detail_fails() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/group/switzerland/de/jobs":
            return httpx.Response(200, text=listing_html([record], total=1))
        return httpx.Response(503, text="unavailable")

    job = (
        LyrecoSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == record["title"]
    assert job.location == "Dietikon ZH, Switzerland"
    assert job.apply_url == job_url(record)
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (listing_html([], total=0, title="Generic careers"), "unexpected identity"),
        (listing_html([vacancy_record(0)], total=1, facet_total=2), "filter"),
        (
            listing_html([vacancy_record(0)], total=1, location="Dintikon AG"),
            "out-of-scope",
        ),
    ],
)
def test_lyreco_rejects_untrusted_catalogs(page_html: str, message: str) -> None:
    parser = LyrecoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page_html))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_lyreco_rejects_duplicate_and_oversized_catalogs() -> None:
    record = vacancy_record(0)
    duplicate = LyrecoSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([record, record], total=2))
        )
    )
    oversized = LyrecoSwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([record, vacancy_record(1)], total=2),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="does not reconcile"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_lyreco_enforces_page_limit() -> None:
    records = [vacancy_record(index) for index in range(11)]
    parser = LyrecoSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(records[:10], total=11))
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="requires 2 pages"):
        parser.search(LinkedInSearchRequest())


def test_lyreco_keeps_listing_when_detail_is_invalid() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/group/switzerland/de/jobs":
            return httpx.Response(200, text=listing_html([record], total=1))
        return httpx.Response(200, text=detail_html(record, country="Germany"))

    job = (
        LyrecoSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.title == record["title"]
    assert "invalid JobPosting metadata" in str(job.raw["detail_error"])


def test_lyreco_accepts_explicit_empty_catalog() -> None:
    result = LyrecoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html([], total=0)))
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 Lyreco Switzerland vacancies")


def test_lyreco_wraps_listing_request_failures() -> None:
    parser = LyrecoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_lyreco_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["lyreco_switzerland"]

    assert isinstance(parser, LyrecoSwitzerlandJobsParser)
    assert parser.base_url == settings.lyreco_switzerland_jobs_base_url
    assert parser.max_pages == settings.lyreco_switzerland_jobs_max_pages
    assert parser.max_jobs == settings.lyreco_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.lyreco_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Lyreco Switzerland", "filters": {}},
            "sources": ["lyreco_switzerland", "lyreco_switzerland"],
        }
    )
    assert request.sources == ["lyreco_switzerland"]

    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["external_id"],
                "title": record["title"],
                "location": "Dietikon ZH, Switzerland",
                "employment_type": record["employment_type"],
                "url": job_url(record),
            }
        ),
        job_id=f"lyreco_switzerland-{record['external_id']}",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Lyreco Switzerland import"
    assert stored["company"] == "Lyreco Switzerland AG"
