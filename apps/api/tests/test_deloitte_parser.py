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
from app.services.parsers.companies.deloitte import DeloitteJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(job_id: int) -> str:
    return f"""
    <article class="article article--result">
      <header class="article__header">
        <div class="article__header__text">
          <h3><a href="/CHCareers/JobDetail/Role-{job_id}/{job_id}">Role {job_id}</a></h3>
          <div class="article__header__text__subtitle">
            <span>Zurich</span><span>Consulting</span><span>Posted: 29 Jun 2026</span>
          </div>
        </div>
      </header>
      <a class="button button--primary" href="/CHCareers/Login?jobId={job_id}">Apply</a>
    </article>
    """


def listing_html(ids: list[int], *, start: int, end: int, total: int) -> str:
    cards = "".join(listing_card(job_id) for job_id in ids)
    return f"""
    <html><body>
      <div class="list-controls--top">
        <div class="list-controls__text__legend">{start}-{end} of {total} results{{</div>
      </div>
      {cards}
    </body></html>
    """


def detail_html(job_id: int) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": f"Role {job_id}",
        "datePosted": "2026-06-29",
    }
    return f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <article class="article article--details">
        <h2>Basic information</h2>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">Business line:</div>
          <div class="article__content__view__field__value">Tax &amp; Legal</div>
        </div>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">City:</div>
          <div class="article__content__view__field__value">Basel, Geneva, Zurich</div>
        </div>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">Experience level:</div>
          <div class="article__content__view__field__value">Experienced</div>
        </div>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">Working time percentage:</div>
          <div class="article__content__view__field__value">80% - 100%</div>
        </div>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">Date published:</div>
          <div class="article__content__view__field__value">29-Jun-2026</div>
        </div>
        <div class="article__content__view__field">
          <div class="article__content__view__field__label">Req #:</div>
          <div class="article__content__view__field__value">{job_id}</div>
        </div>
      </article>
      <article class="article article--details">
        <h2>Job description</h2>
        <div class="article__content__view__field__value">
          <p>Help clients solve difficult problems.</p>
          <h3>Your role</h3>
          <ul><li>Build reliable services.</li><li>Support delivery teams.</li></ul>
        </div>
      </article>
      <article class="article article--actions">
        <a class="button button--primary" href="/CHCareers/Login?jobId={job_id}">Apply</a>
      </article>
    </body></html>
    """


def test_deloitte_scans_full_catalog_and_enriches_every_record() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/CHCareers/SearchJobs/":
            offset = int(request.url.params["jobOffset"])
            ids = list(range(23951, 23957)) if offset == 0 else [23957, 23958]
            start = offset + 1
            return httpx.Response(
                200,
                text=listing_html(ids, start=start, end=start + len(ids) - 1, total=8),
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = DeloitteJobsParser(
        base_url="https://apply.deloitte.test/CHCareers/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 8 Deloitte vacancies across 2 catalog pages"
    assert len(requests) == 10
    assert len(result.jobs) == 8
    first = result.jobs[0]
    assert first.source == "deloitte"
    assert first.title == "Role 23951"
    assert first.company == "Deloitte"
    assert first.location == "Basel, Geneva, Zurich"
    assert first.url == "https://apply.deloitte.test/CHCareers/JobDetail/Role-23951/23951"
    assert first.apply_url == "https://apply.deloitte.test/CHCareers/Login?jobId=23951"
    assert first.posted_at == "2026-06-29"
    assert first.employment_type == "80% - 100%"
    assert first.seniority == "Experienced"
    assert first.description == (
        "Help clients solve difficult problems.\n\n"
        "Your role\n\n"
        "- Build reliable services.\n"
        "- Support delivery teams."
    )
    assert first.raw["id"] == "23951"
    assert first.raw["business_line"] == "Consulting"
    assert first.raw["detail"]["business_line"] == "Tax & Legal"
    assert first.raw["detail"]["requisition_id"] == "23951"


def test_deloitte_repeats_shifted_catalog_pages_until_all_ids_are_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if "/JobDetail/" in request.url.path:
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
            return httpx.Response(200, text=detail_html(job_id))

        offset = int(request.url.params["jobOffset"])
        if offset == 0:
            first_page_calls += 1
            ids = [1, 2, 3, 4, 5, 6]
        elif first_page_calls == 1:
            ids = [6, 7]
        else:
            ids = [7, 8]
        return httpx.Response(
            200,
            text=listing_html(
                ids,
                start=offset + 1,
                end=offset + len(ids),
                total=8,
            ),
        )

    parser = DeloitteJobsParser(
        base_url="https://apply.deloitte.test/CHCareers/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 8
    assert first_page_calls == 2
    assert result.message == "Scanned 8 Deloitte vacancies across 4 catalog pages"


def test_deloitte_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/CHCareers/SearchJobs/":
            return httpx.Response(
                200,
                text=listing_html([23951], start=1, end=1, total=1),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = DeloitteJobsParser(
        base_url="https://apply.deloitte.test/CHCareers/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Role 23951"
    assert job.location == "Zurich"
    assert job.posted_at == "2026-06-29"
    assert job.description is None
    assert job.apply_url == "https://apply.deloitte.test/CHCareers/Login?jobId=23951"
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_deloitte_rejects_listing_without_catalog_contract() -> None:
    parser = DeloitteJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="result range"):
        parser.search(LinkedInSearchRequest())


def test_deloitte_enforces_catalog_page_limit() -> None:
    parser = DeloitteJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [1, 2, 3, 4, 5, 6],
                    start=1,
                    end=6,
                    total=7,
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_deloitte_is_registered_as_a_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["deloitte"]
    assert isinstance(parser, DeloitteJobsParser)
    assert parser.base_url == settings.deloitte_jobs_base_url
    assert parser.max_pages == settings.deloitte_jobs_max_pages
    assert parser.max_catalog_passes == settings.deloitte_jobs_max_catalog_passes
    assert parser.detail_workers == settings.deloitte_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Deloitte", "filters": {}},
            "sources": ["deloitte", "deloitte"],
        }
    )
    assert request.sources == ["deloitte"]


def test_deloitte_jobs_render_as_direct_company_imports() -> None:
    parser = DeloitteJobsParser()
    job = parser.normalize_job(
        {
            "id": "23951",
            "title": "Assistant Manager",
            "location": "Zurich",
            "url": "https://apply.deloitte.ch/CHCareers/JobDetail/Assistant-Manager/23951",
            "apply_url": "https://apply.deloitte.ch/CHCareers/Login?jobId=23951",
            "posted_at": "2026-06-29",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="deloitte-23951",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Deloitte import"
    assert stored["id"] == "deloitte-23951"
