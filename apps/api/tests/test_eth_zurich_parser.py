from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.eth_zurich import (
    EthZurichJobsParser,
    parse_job_details,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(
    *,
    listing_id: int,
    job_id: str,
    title: str,
    details: str,
    department: str,
) -> str:
    return f"""
    <div data-key="{listing_id}">
      <li class="job-ad__item__wrapper">
        <a href="/job/view/{job_id}" class="job-ad__item__link">
          <h3 class="job-ad__item__title">{title}</h3>
          <div class="job-ad__item__details">{details}</div>
          <div class="job-ad__item__company">08.08.2026 | {department}</div>
        </a>
      </li>
    </div>
    """


def listing_html(cards: list[str], *, total: int) -> str:
    return f"""
    <html><body>
      <section class="intro"><h2>{total}&nbsp;offene Stellen</h2></section>
      <ul id="w1" class="job-ad__wrapper">{"".join(cards)}</ul>
    </body></html>
    """


def detail_html(
    *,
    title: str,
    details: str,
    apply_url: str,
) -> str:
    return f"""
    <html><body>
      <div class="application main-center">
        <section class="description" aria-labelledby="job-title">
          <h1 class="description__title" id="job-title">{title}</h1>
          <h4 aria-label="{details}">{details}</h4>
          <div class="paragraph description__paragraph" role="region"
               aria-label="Project background">
            <p>Build reliable research infrastructure.</p>
          </div>
          <div role="region" aria-label="Job description">
            <h2 id="job-description">Job description</h2>
            <div class="paragraph description__paragraph">
              <p>You will operate scientific platforms.</p>
              <ul><li>Automate services.</li><li>Support researchers.</li></ul>
            </div>
          </div>
          <div role="region" aria-label="Profile">
            <h2 id="profile">Profile</h2>
            <p>Experience with Python and Linux.</p>
          </div>
          <iframe title="Workplace - Binzmühlestrasse 8092 Zurich"></iframe>
        </section>
      </div>
      <a href="{apply_url}" class="application__button--link">Apply online now</a>
    </body></html>
    """


def test_eth_zurich_scans_and_enriches_complete_catalog() -> None:
    platform_title = "Platform Engineer"
    doctoral_title = "Doctoral Researcher"
    page = listing_html(
        [
            listing_card(
                listing_id=101,
                job_id="JOPG_ethz_platform",
                title=platform_title,
                details="80%-100%, Zurich, permanent",
                department="Scientific IT Services",
            ),
            listing_card(
                listing_id=102,
                job_id="11996",
                title=doctoral_title,
                details="70%-80%, Zurich, fixed-term",
                department="Technology Marketing",
            ),
        ],
        total=2,
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(200, text=page)
        if request.url.path.endswith("JOPG_ethz_platform"):
            return httpx.Response(
                200,
                text=detail_html(
                    title=platform_title,
                    details="80%-100%, Zurich, permanent",
                    apply_url="https://apply.example/platform",
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                title=doctoral_title,
                details="70%-80%, Zurich, fixed-term",
                apply_url="mailto:professor@example.org",
            ),
        )

    parser = EthZurichJobsParser(
        base_url="https://jobs.ethz.test/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 ETH Zürich vacancies from the full catalog page")
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "eth_zurich"
    assert first.title == platform_title
    assert first.company == "ETH Zürich"
    assert first.location == "Zurich"
    assert first.url == "https://jobs.ethz.test/job/view/JOPG_ethz_platform"
    assert first.apply_url == "https://apply.example/platform"
    assert first.posted_at == "2026-08-08"
    assert first.employment_type == "80%-100%"
    assert first.description == (
        "Project background\n\n"
        "Build reliable research infrastructure.\n\n"
        "Job description\n\n"
        "You will operate scientific platforms.\n\n"
        "- Automate services.\n"
        "- Support researchers.\n\n"
        "Profile\n\n"
        "Experience with Python and Linux."
    )
    assert first.raw["department"] == "Scientific IT Services"
    assert first.raw["detail"]["workplace"] == "Binzmühlestrasse 8092 Zurich"
    assert result.jobs[1].apply_url == "mailto:professor@example.org"


def test_eth_zurich_preserves_listing_when_detail_request_fails() -> None:
    page = listing_html(
        [
            listing_card(
                listing_id=101,
                job_id="JOPG_ethz_platform",
                title="Platform Engineer",
                details="80%-100%, Zurich, permanent",
                department="Scientific IT Services",
            )
        ],
        total=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text=page)
        return httpx.Response(503, text="temporarily unavailable")

    parser = EthZurichJobsParser(
        base_url="https://jobs.ethz.test/",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Platform Engineer"
    assert job.location == "Zurich"
    assert job.employment_type == "80%-100%"
    assert job.description is None
    assert job.apply_url is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_eth_zurich_accepts_apprenticeships_without_a_workload() -> None:
    assert parse_job_details("Zürich, Lehrstelle") == (
        None,
        "Zürich",
        "Lehrstelle",
    )


def test_eth_zurich_rejects_listing_without_catalog_contract() -> None:
    parser = EthZurichJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        parser.search(LinkedInSearchRequest())


def test_eth_zurich_rejects_incomplete_catalog() -> None:
    page = listing_html(
        [
            listing_card(
                listing_id=101,
                job_id="JOPG_ethz_platform",
                title="Platform Engineer",
                details="80%-100%, Zurich, permanent",
                department="Scientific IT Services",
            )
        ],
        total=2,
    )
    parser = EthZurichJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="declared 2"):
        parser.search(LinkedInSearchRequest())


def test_eth_zurich_wraps_listing_request_failures() -> None:
    parser = EthZurichJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_eth_zurich_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["eth_zurich"]
    assert isinstance(parser, EthZurichJobsParser)
    assert parser.base_url == settings.eth_zurich_jobs_base_url
    assert parser.detail_workers == settings.eth_zurich_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "ETH Zürich", "filters": {}},
            "sources": ["eth_zurich", "eth_zurich"],
        }
    )
    assert request.sources == ["eth_zurich"]


def test_eth_zurich_jobs_render_as_direct_company_imports() -> None:
    parser = EthZurichJobsParser()
    job = parser.normalize_job(
        {
            "id": "JOPG_ethz_platform",
            "title": "Platform Engineer",
            "location": "Zurich",
            "workload": "80%-100%",
            "posted_at": "08.08.2026",
            "url": "https://jobs.ethz.ch/job/view/JOPG_ethz_platform",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="eth_zurich-JOPG_ethz_platform",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "ETH Zürich import"
    assert stored["id"] == "eth_zurich-JOPG_ethz_platform"
