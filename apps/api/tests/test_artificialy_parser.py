from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.artificialy import (
    ArtificialyJobsParser,
    normalize_job,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)

    def json(self) -> Any:
        raise AssertionError("Artificialy response is HTML")


def vacancy_card(
    job_id: str,
    title: str,
    description: str,
    *,
    location: str = "Lugano",
    employment_type: str = "Full-time",
    host: str = "www.linkedin.com",
    rel: str = "noopener noreferrer",
) -> str:
    return f"""
    <div class="bg-white rounded-lg border flex flex-col h-full">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2"><svg></svg><span>{location}</span></div>
        <span>{employment_type}</span>
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      <div class="mt-auto">
        <a href="https://{host}/jobs/view/{job_id}" target="_blank" rel="{rel}">
          View on LinkedIn <svg></svg>
        </a>
      </div>
    </div>
    """


def careers_html(cards: list[str], *, heading: str = "Shape the Future of AI with Us") -> str:
    return f"""
    <html><body><main>
      <h1>{heading}</h1>
      <section id="section-careers_openings">
        <div><h2>Open Positions</h2><div class="grid">{"".join(cards)}</div></div>
      </section>
    </main></body></html>
    """


def official_cards() -> list[str]:
    return [
        vacancy_card(
            "4440007645",
            "AI Engineer",
            "Bring AI solutions from prototype to production.",
        ),
        vacancy_card(
            "4430466105",
            "Head of AI Product",
            "Lead the vision, strategy and roadmap of new products.",
        ),
        vacancy_card(
            "4440003952",
            "AI Scientist - LLM Systems",
            "Design and develop LLM-based solutions.",
        ),
    ]


def test_artificialy_scans_complete_server_rendered_catalog() -> None:
    calls: list[str] = []

    def fetch_page(url: str) -> HtmlResponse:
        calls.append(url)
        return HtmlResponse(careers_html(official_cards()))

    result = ArtificialyJobsParser(fetch_page=fetch_page).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert calls == ["https://www.artificialy.com/career"]
    assert result.message == (
        "Scanned 3 Artificialy vacancies from the complete server-rendered careers catalog"
    )
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "artificialy"
    assert first.title == "AI Engineer"
    assert first.company == "Artificialy SA"
    assert first.location == "Lugano"
    assert first.employment_type == "Full-time"
    assert first.description == "Bring AI solutions from prototype to production."
    assert first.url == "https://www.linkedin.com/jobs/view/4440007645"
    assert first.apply_url == first.url
    assert first.raw["id"] == "4440007645"


def test_artificialy_rejects_wrong_page_identity_and_missing_catalog() -> None:
    wrong_identity = ArtificialyJobsParser(
        fetch_page=lambda _: HtmlResponse(careers_html(official_cards(), heading="Generic careers"))
    )
    missing_catalog = ArtificialyJobsParser(
        fetch_page=lambda _: HtmlResponse(
            "<html><body><main><h1>Shape the Future of AI with Us</h1></main></body></html>"
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="missing its official catalog"):
        missing_catalog.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("card", "message"),
    [
        (
            vacancy_card(
                "4440007645",
                "AI Engineer",
                "Build AI.",
                location="Berlin",
            ),
            "out-of-scope",
        ),
        (
            vacancy_card(
                "4440007645",
                "AI Engineer",
                "Build AI.",
                host="evil.example",
            ),
            "out-of-scope",
        ),
        (
            vacancy_card(
                "4440007645",
                "AI Engineer",
                "Build AI.",
                rel="nofollow",
            ),
            "out-of-scope",
        ),
    ],
)
def test_artificialy_rejects_untrusted_cards(card: str, message: str) -> None:
    parser = ArtificialyJobsParser(fetch_page=lambda _: HtmlResponse(careers_html([card])))
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_artificialy_rejects_duplicate_and_oversized_catalogs() -> None:
    card = official_cards()[0]
    duplicate = ArtificialyJobsParser(fetch_page=lambda _: HtmlResponse(careers_html([card, card])))
    oversized = ArtificialyJobsParser(
        max_jobs=1,
        fetch_page=lambda _: HtmlResponse(careers_html(official_cards())),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_artificialy_accepts_explicit_empty_catalog() -> None:
    page_html = """
    <html><body><main>
      <h1>Shape the Future of AI with Us</h1>
      <section id="section-careers_openings">
        <h2>Open Positions</h2><p>No current open positions</p>
      </section>
    </main></body></html>
    """
    result = ArtificialyJobsParser(fetch_page=lambda _: HtmlResponse(page_html)).search(
        LinkedInSearchRequest()
    )

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 Artificialy vacancies")


def test_artificialy_wraps_request_failures() -> None:
    def fail(_: str) -> HtmlResponse:
        raise RuntimeError("Cloudflare unavailable")

    parser = ArtificialyJobsParser(fetch_page=fail)
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_artificialy_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["artificialy"]

    assert isinstance(parser, ArtificialyJobsParser)
    assert parser.base_url == settings.artificialy_jobs_base_url
    assert parser.timeout_seconds == settings.artificialy_jobs_timeout_seconds
    assert parser.max_jobs == settings.artificialy_jobs_max_jobs
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Artificialy", "filters": {}},
            "sources": ["artificialy", "artificialy"],
        }
    )
    assert request.sources == ["artificialy"]


def test_artificialy_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": "4440007645",
        "title": "AI Engineer",
        "company": "Artificialy SA",
        "location": "Lugano",
        "employment_type": "Full-time",
        "description": "Build AI systems.",
        "url": "https://www.linkedin.com/jobs/view/4440007645",
        "apply_url": "https://www.linkedin.com/jobs/view/4440007645",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="artificialy-4440007645",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Artificialy SA import"
    assert stored["company"] == "Artificialy SA"
