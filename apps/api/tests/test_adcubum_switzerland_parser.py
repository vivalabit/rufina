from __future__ import annotations

import html
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.adcubum_switzerland import (
    AdcubumSwitzerlandJobsParser,
    normalize_job,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

TENANT_ID = "66503e5e-1add-4934-ac5e-89a651ebd04e"


def vacancy_record(
    index: int,
    *,
    country: str = "CH",
    city: str | None = None,
    company: str | None = None,
) -> dict[str, str]:
    job_id = f"{index + 1:08x}-48eb-c741-767d-{index + 20:012x}"
    publication_id = f"{index + 101:08x}-f01c-d3e2-ff29-{index + 40:012x}"
    return {
        "id": job_id,
        "publicationId": publication_id,
        "title": f"Software Engineer {index}",
        "city": city or ("Wallisellen" if country == "CH" else "Zagreb"),
        "country": country,
        "category": "100",
        "companyName": company or ("Adcubum AG" if country == "CH" else "Adcubum d.o.o"),
        "publicationStart": f"2026-08-{index + 1:02d}",
        "publicationEnd": "",
        "publicationUrl": (
            "https://app.jobportal.abaservices.ch/job-advertisement/"
            f"{TENANT_ID}/{publication_id}?jp=ABACUS"
        ),
        "language": "en",
    }


def job_url(record: dict[str, str]) -> str:
    return f"https://www.adcubum.com/en/job/detail/{record['id']}"


def listing_html(
    records: list[dict[str, str]],
    *,
    dom_records: list[dict[str, str]] | None = None,
    title: str = (
        "Leading software manufacturer for the international insurance industry - Adcubum AG"
    ),
    language: str = "en",
) -> str:
    flight_payload = [
        "$",
        "main",
        None,
        {"children": ["$", "$L21", None, {"language": "en", "jobs": records}]},
    ]
    flight_call = json.dumps([1, f"6:{json.dumps(flight_payload)}"])
    cards = "".join(
        f"""
        <li><a href="/en/job/detail/{record["id"]}">
          <div><h3>{html.escape(record["title"])}</h3>
            <div class="flex items-center"><span>{record["city"]}</span></div>
          </div><span>Show Job</span>
        </a></li>
        """
        for record in (records if dom_records is None else dom_records)
    )
    return f"""
    <html lang="{language}"><head><title>{title}</title>
      <meta property="og:title" content="{title}">
    </head><body><header><a href="/de/job/list">DE</a></header>
      <main><input type="text" placeholder="Search jobs..."><ul role="list">{cards}</ul></main>
      <script>self.__next_f.push({flight_call})</script>
    </body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    title: str | None = None,
    city: str | None = None,
    apply_id: str | None = None,
) -> str:
    detail_title = title or record["title"]
    detail_city = city or record["city"]
    application_id = apply_id or record["id"]
    description = (
        "We build market-leading insurance software for customers throughout Switzerland. "
        "You design reliable services, collaborate with product and engineering teams, and "
        "take ownership from discovery through delivery. We offer flexible working models, "
        "continuous learning, and an experienced international team."
    )
    return f"""
    <html lang="en"><head><title>{html.escape(detail_title)}</title>
      <meta property="og:title" content="{html.escape(detail_title)}">
    </head><body><main><div><div>
      <h1>{html.escape(detail_title)}</h1>
      <div class="mb-12">
        <div class="flex">{detail_city}</div>
        <div><div class="flex">Full-time</div></div>
      </div>
      <div><p>{description}</p></div>
      <div><h2>Your tasks</h2><p>Build robust software and support our customers.</p></div>
      <div class="mt-12"><a href="/en/job/form/{application_id}">Apply now</a></div>
    </div></div></main></body></html>
    """


def test_adcubum_reconciles_global_catalog_and_enriches_only_swiss_jobs() -> None:
    swiss_one = vacancy_record(0)
    croatian = vacancy_record(1, country="HR")
    swiss_two = vacancy_record(2, city="St. Gallen")
    records = [swiss_one, croatian, swiss_two]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/en/job/list":
            return httpx.Response(200, text=listing_html(records))
        record = next(item for item in records if request.url.path == httpx.URL(job_url(item)).path)
        return httpx.Response(200, text=detail_html(record))

    result = AdcubumSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.message == (
        "Scanned 2 Adcubum Switzerland vacancies from the complete global catalog of 3 jobs"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "adcubum_switzerland"
    assert first.company == "Adcubum AG"
    assert first.location == "Wallisellen, Switzerland"
    assert first.url == job_url(swiss_one)
    assert first.apply_url == f"https://www.adcubum.com/en/job/form/{swiss_one['id']}"
    assert first.posted_at == "2026-08-01"
    assert first.employment_type == "Full-time"
    assert first.seniority is None
    assert first.description and first.description.startswith("We build market-leading")
    assert first.raw["global_catalog_total"] == 3
    assert first.raw["swiss_catalog_total"] == 2
    assert first.raw["publication_id"] == swiss_one["publicationId"]


def test_adcubum_preserves_verified_listing_when_detail_fails() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/job/list":
            return httpx.Response(200, text=listing_html([record]))
        return httpx.Response(503, text="unavailable")

    job = (
        AdcubumSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == record["title"]
    assert job.location == "Wallisellen, Switzerland"
    assert job.apply_url == job_url(record)
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (listing_html([], title="Generic careers"), "unexpected identity"),
        (
            listing_html([vacancy_record(0)], dom_records=[]),
            "does not reconcile",
        ),
        (
            listing_html(
                [vacancy_record(0)],
                dom_records=[{**vacancy_record(0), "city": "Zagreb"}],
            ),
            "does not match",
        ),
    ],
)
def test_adcubum_rejects_untrusted_catalogs(page_html: str, message: str) -> None:
    parser = AdcubumSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page_html))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_adcubum_rejects_duplicate_and_oversized_catalogs() -> None:
    record = vacancy_record(0)
    duplicate = AdcubumSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([record, record]))
        )
    )
    oversized = AdcubumSwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([record, vacancy_record(1, country="HR")]),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_adcubum_rejects_unexpected_swiss_hiring_company() -> None:
    record = vacancy_record(0, company="Different AG")
    parser = AdcubumSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html([record])))
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected hiring company"):
        parser.search(LinkedInSearchRequest())


def test_adcubum_keeps_listing_when_detail_is_invalid() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/job/list":
            return httpx.Response(200, text=listing_html([record]))
        return httpx.Response(200, text=detail_html(record, apply_id=vacancy_record(2)["id"]))

    job = (
        AdcubumSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.title == record["title"]
    assert "application form" in str(job.raw["detail_error"])


def test_adcubum_accepts_explicit_empty_catalog() -> None:
    result = AdcubumSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html([])))
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.endswith("complete global catalog of 0 jobs")


def test_adcubum_wraps_listing_request_failures() -> None:
    parser = AdcubumSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_adcubum_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["adcubum_switzerland"]

    assert isinstance(parser, AdcubumSwitzerlandJobsParser)
    assert parser.base_url == settings.adcubum_switzerland_jobs_base_url
    assert parser.max_jobs == settings.adcubum_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.adcubum_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Adcubum Switzerland", "filters": {}},
            "sources": ["adcubum_switzerland", "adcubum_switzerland"],
        }
    )
    assert request.sources == ["adcubum_switzerland"]

    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["id"],
                "title": record["title"],
                "location": "Wallisellen, Switzerland",
                "posted_at": record["publicationStart"],
                "url": job_url(record),
            }
        ),
        job_id=f"adcubum_switzerland-{record['id']}",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Adcubum Switzerland import"
    assert stored["company"] == "Adcubum AG"
