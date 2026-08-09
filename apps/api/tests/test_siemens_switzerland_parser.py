from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.siemens_switzerland import (
    SiemensSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(job_id: int, *, title: str | None = None) -> str:
    return f"""
    <article class="article article--result">
      <div class="article__header__text">
        <h3><a class="link" href="/de_DE/externaljobs/JobDetail/{job_id}">
          {title or f'Automation Engineer {job_id} 80–100%'}
        </a></h3>
        <div class="article__header__text__subtitle">
          <span class="list-item-location">Zug, Zug, Switzerland</span>
          <span class="list-item-jobId">Job-ID: {job_id}</span>
          <span class="list-item-family">Engineering</span>
        </div>
      </div>
    </article>
    """


def listing_html(ids: list[int], *, start: int, end: int, total: int) -> str:
    cards = "".join(listing_card(job_id) for job_id in ids)
    return f"""
    <html><body>
      <div class="list-controls--top">
        <div class="list-controls__text__legend" aria-label="{total} Ergebnisse">
          {start} - {end} von {total} Ergebnisse
        </div>
      </div>
      {cards}
    </body></html>
    """


def detail_html(job_id: int) -> str:
    def field(label: str, value: str) -> str:
        return f"""
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">{label}</div>
          <div class="article__content__view__field__value">{value}</div>
        </div>
        """

    fields = "".join(
        [
            field("Job ID", str(job_id)),
            field("Veröffentlicht seit", "05-Aug-2026"),
            field("Organization", "Smart Infrastructure"),
            field("Tätigkeitsbereich", "Engineering"),
            field("Unternehmen", "Siemens Schweiz AG"),
            field("Erfahrungsniveau", "Berufserfahren"),
            field("Beschäftigungsart", "Vollzeit"),
            field("Arbeitsmodell", "Hybrid"),
            field("Vertragsart", "Unbefristet"),
            field("Standort(e)", "Zug - Zug - Schweiz"),
        ]
    )
    return f"""
    <html><body>
      <section>
        <h3 class="section__header__text__title">
          Automation Engineer {job_id} 80–100%
        </h3>
      </section>
      <article class="article article--details">{fields}</article>
      <article class="article article--details">
        <div class="job-section editable" id="youtube_link">
          <p>Gemeinsam verbinden wir die reale und die digitale Welt.</p>
          <h3>Deine neuen Aufgaben</h3>
          <ul><li>Build reliable systems.</li><li>Support customers.</li></ul>
        </div>
      </article>
      <article class="article article--actions">
        <a class="button button--hero"
           href="/de_DE/externaljobs/ApplicationMethods?folderId={job_id}">
          Bewerben
        </a>
      </article>
    </body></html>
    """


def test_siemens_switzerland_scans_full_catalog_and_enriches_records() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/SearchJobs/"):
            offset = int(request.url.params.get("folderOffset", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = SiemensSwitzerlandJobsParser(
        base_url=(
            "https://jobs.siemens.test/de_DE/externaljobs/SearchJobs/"
            "?42386=%5B812129%5D&folderRecordsPerPage=2"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Siemens Schweiz vacancies from 3 catalog records "
        "across 2 page requests"
    )
    listing_requests = [r for r in requests if r.url.path.endswith("/SearchJobs/")]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["42386"] == "[812129]"
    assert "folderOffset" not in listing_requests[0].url.params
    assert listing_requests[1].url.params["folderOffset"] == "2"
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "siemens_switzerland"
    assert first.title == "Automation Engineer 101 80–100%"
    assert first.company == "Siemens Schweiz AG"
    assert first.location == "Zug - Zug - Schweiz"
    assert first.url == "https://jobs.siemens.test/de_DE/externaljobs/JobDetail/101"
    assert first.apply_url == (
        "https://jobs.siemens.test/de_DE/externaljobs/"
        "ApplicationMethods?folderId=101"
    )
    assert first.posted_at == "2026-08-05"
    assert first.employment_type == "80-100%"
    assert first.seniority == "Berufserfahren"
    assert first.description == (
        "Gemeinsam verbinden wir die reale und die digitale Welt.\n\n"
        "Deine neuen Aufgaben\n\n"
        "- Build reliable systems.\n"
        "- Support customers."
    )
    assert first.raw["family"] == "Engineering"
    assert first.raw["detail"]["work_model"] == "Hybrid"


def test_siemens_switzerland_retries_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if not request.url.path.endswith("/SearchJobs/"):
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
            return httpx.Response(200, text=detail_html(job_id))

        offset = int(request.url.params.get("folderOffset", "0"))
        if offset == 0:
            first_page_calls += 1
            ids = [101, 102]
            start, end = 1, 2
        else:
            ids = [102] if first_page_calls == 1 else [103]
            start = end = 3
        return httpx.Response(
            200,
            text=listing_html(ids, start=start, end=end, total=3),
        )

    parser = SiemensSwitzerlandJobsParser(
        base_url="https://jobs.siemens.test/de_DE/externaljobs/SearchJobs/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_siemens_switzerland_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SearchJobs/"):
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SiemensSwitzerlandJobsParser(
        base_url="https://jobs.siemens.test/de_DE/externaljobs/SearchJobs/",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Automation Engineer 101 80–100%"
    assert job.company == "Siemens Schweiz AG"
    assert job.location == "Zug, Zug, Switzerland"
    assert job.employment_type == "80-100%"
    assert job.description is None
    assert job.apply_url is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_siemens_switzerland_rejects_listing_without_catalog_contract() -> None:
    parser = SiemensSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_siemens_switzerland_enforces_catalog_page_limit() -> None:
    parser = SiemensSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_siemens_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["siemens_switzerland"]
    assert isinstance(parser, SiemensSwitzerlandJobsParser)
    assert parser.base_url == settings.siemens_switzerland_jobs_base_url
    assert parser.max_pages == settings.siemens_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.siemens_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == settings.siemens_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Siemens Schweiz", "filters": {}},
            "sources": ["siemens_switzerland", "siemens_switzerland"],
        }
    )
    assert request.sources == ["siemens_switzerland"]


def test_siemens_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = SiemensSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "101",
            "title": "Automation Engineer",
            "location": "Zug, Switzerland",
            "url": "https://jobs.siemens.com/de_DE/externaljobs/JobDetail/101",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="siemens_switzerland-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Siemens Schweiz import"
    assert stored["id"] == "siemens_switzerland-101"
