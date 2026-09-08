from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.rdm_switzerland import (
    RDM_SWITZERLAND_JOBS_URL,
    RdmSwitzerlandJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

DEVELOPMENT_SLUG = "development-test-engineer-rd"
WAREHOUSE_SLUG = "teamleiterin-warehouse"


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)

    def json(self) -> Any:
        raise AssertionError("R&M response is HTML")


def job_url(slug: str) -> str:
    return f"https://www.rdm.com/jobs/{slug}/"


def vacancy_card(
    slug: str,
    title: str,
    *,
    category: str = "Research & Development",
    location: str = "Wetzikon, Switzerland",
    host: str = "www.rdm.com",
) -> str:
    return f"""
    <div class="col-12 col-md-6 col-lg-4 jobs card-col">
      <div class="card-wrapper tiles-default">
        <a href="https://{host}/jobs/{slug}/">
          <div class="single-card-column event">
            <div class="card-subtitle">{category}</div>
            <div class="card-text"><h3>{title}</h3></div>
            <div class="card-position">{location}</div>
          </div>
        </a>
      </div>
    </div>
    """


def listing_html(
    cards: list[str],
    *,
    filtered_total: int | None = None,
    global_total: int = 15,
    title: str = "Vacancies at R&M - R&M",
    heading: str = "Vacancies at R&M",
    canonical: str = "https://www.rdm.com/career/jobs/",
) -> str:
    filtered_total = len(cards) if filtered_total is None else filtered_total
    return f"""
    <html><head><title>{title}</title><link rel="canonical" href="{canonical}"></head>
    <body><main>
      <h1>{heading}</h1>
      <div class="row"><div class="col-6">{filtered_total} of {global_total} Jobs</div></div>
      <div class="row">{"".join(cards)}</div>
      <div class="long-card col-12"><div class="card-wrapper tiles-default">
        <a href="https://www.rdm.com/career/"><h3>Career</h3></a>
      </div></div>
    </main></body></html>
    """


def detail_html(
    slug: str,
    title: str,
    *,
    post_id: str = "907278",
    location: str = "Wetzikon, Switzerland",
    employment_type: str = "Full-time",
    canonical: str | None = None,
    description: str = (
        "Aufgaben Entwicklung und Prüfung innovativer Verbindungstechnik. "
        "Anforderungen Fundierte Kenntnisse in Messtechnik und Datenkommunikation. "
        "Wir bieten eine anspruchsvolle Aufgabe mit Gestaltungsfreiraum und neuen Ideen."
    ),
) -> str:
    return f"""
    <html><head><link rel="canonical" href="{canonical or job_url(slug)}"></head>
    <body class="single single-jobs postid-{post_id}" data-pageid="{post_id}">
      <h1>{title}</h1>
      <div class="job-info">
        <p>{location}</p><p>{employment_type}</p>
        <a class="default-button" popup="applicationForm">Apply</a>
      </div>
      <section class="popup" id="applicationForm"><form></form></section>
      <div class="main-content wysiwyg"><p>{description}</p></div>
    </body></html>
    """


def official_cards() -> list[str]:
    return [
        vacancy_card(DEVELOPMENT_SLUG, "Development &amp; Test Engineer R&amp;D"),
        vacancy_card(
            WAREHOUSE_SLUG,
            "Teamleiter:in Warehouse",
            category="Logistics",
        ),
    ]


def test_rdm_module_import_does_not_initialize_browser_fetcher() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.services.parsers.companies.rdm_switzerland; "
                "assert 'scrapling.fetchers' not in sys.modules"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_rdm_collects_complete_filtered_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def fetch_page(url: str) -> HtmlResponse:
        calls.append(url)
        if url == RDM_SWITZERLAND_JOBS_URL:
            return HtmlResponse(listing_html(official_cards()))
        if url == job_url(DEVELOPMENT_SLUG):
            return HtmlResponse(
                detail_html(
                    DEVELOPMENT_SLUG,
                    "Development &amp; Test Engineer R&amp;D",
                    post_id="907278",
                )
            )
        return HtmlResponse(
            detail_html(
                WAREHOUSE_SLUG,
                "Teamleiter:in Warehouse",
                post_id="907279",
            )
        )

    result = RdmSwitzerlandJobsParser(
        fetch_page=fetch_page,
        detail_workers=2,
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls[0] == RDM_SWITZERLAND_JOBS_URL
    assert sorted(calls[1:]) == sorted([job_url(DEVELOPMENT_SLUG), job_url(WAREHOUSE_SLUG)])
    assert result.message == (
        "Scanned 2 R&M Switzerland vacancies from the complete verified public careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "rdm_switzerland"
    assert first.title == "Development & Test Engineer R&D"
    assert first.company == "Reichle & De-Massari AG"
    assert first.location == "Wetzikon, Switzerland"
    assert first.url == job_url(DEVELOPMENT_SLUG)
    assert first.apply_url == job_url(DEVELOPMENT_SLUG)
    assert first.employment_type == "Full-time"
    assert first.description and first.description.startswith("Aufgaben Entwicklung")
    assert first.raw["id"] == "907278"
    assert first.raw["category"] == "Research & Development"
    assert first.raw["filtered_total"] == 2
    assert first.raw["global_total"] == 15


def test_rdm_preserves_verified_listing_when_detail_fails() -> None:
    card = vacancy_card(DEVELOPMENT_SLUG, "Development & Test Engineer R&D")

    def fetch_page(url: str) -> HtmlResponse:
        if url == RDM_SWITZERLAND_JOBS_URL:
            return HtmlResponse(listing_html([card]))
        raise RuntimeError("detail unavailable")

    job = RdmSwitzerlandJobsParser(fetch_page=fetch_page).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Development & Test Engineer R&D"
    assert job.location == "Wetzikon, Switzerland"
    assert job.apply_url == job_url(DEVELOPMENT_SLUG)
    assert job.description is None
    assert job.raw["id"] == DEVELOPMENT_SLUG
    assert "detail unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (listing_html(official_cards(), title="Generic careers"), "unexpected identity"),
        (
            listing_html(official_cards(), filtered_total=3),
            "does not match its filtered result count",
        ),
        (
            listing_html(
                [
                    vacancy_card(
                        DEVELOPMENT_SLUG,
                        "Development Engineer",
                        location="Berlin, Germany",
                    )
                ]
            ),
            "out-of-scope",
        ),
        (
            listing_html(
                [
                    vacancy_card(
                        DEVELOPMENT_SLUG,
                        "Development Engineer",
                        host="attacker.example",
                    )
                ]
            ),
            "out-of-scope",
        ),
    ],
)
def test_rdm_rejects_malformed_or_untrusted_catalogs(
    page_html: str,
    message: str,
) -> None:
    parser = RdmSwitzerlandJobsParser(fetch_page=lambda _: HtmlResponse(page_html))
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_rdm_rejects_duplicate_and_oversized_catalogs() -> None:
    card = vacancy_card(DEVELOPMENT_SLUG, "Development Engineer")
    duplicate = RdmSwitzerlandJobsParser(
        fetch_page=lambda _: HtmlResponse(listing_html([card, card]))
    )
    oversized = RdmSwitzerlandJobsParser(
        max_jobs=1,
        fetch_page=lambda _: HtmlResponse(listing_html(official_cards())),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_rdm_keeps_listing_when_detail_identity_is_invalid() -> None:
    card = vacancy_card(DEVELOPMENT_SLUG, "Development Engineer")

    def fetch_page(url: str) -> HtmlResponse:
        if url == RDM_SWITZERLAND_JOBS_URL:
            return HtmlResponse(listing_html([card]))
        return HtmlResponse(detail_html(DEVELOPMENT_SLUG, "Different vacancy"))

    job = RdmSwitzerlandJobsParser(fetch_page=fetch_page).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Development Engineer"
    assert job.description is None
    assert "different vacancy title" in str(job.raw["detail_error"])


def test_rdm_accepts_explicit_empty_filtered_catalog() -> None:
    result = RdmSwitzerlandJobsParser(
        fetch_page=lambda _: HtmlResponse(listing_html([], global_total=9))
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 R&M Switzerland vacancies")


def test_rdm_wraps_listing_request_failures() -> None:
    def fail(_: str) -> HtmlResponse:
        raise RuntimeError("browser unavailable")

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        RdmSwitzerlandJobsParser(fetch_page=fail).search(LinkedInSearchRequest())


def test_rdm_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["rdm_switzerland"]

    assert isinstance(parser, RdmSwitzerlandJobsParser)
    assert parser.base_url == settings.rdm_switzerland_jobs_base_url
    assert parser.timeout_seconds == settings.rdm_switzerland_jobs_timeout_seconds
    assert parser.max_jobs == settings.rdm_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.rdm_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "R&M Switzerland", "filters": {}},
            "sources": ["rdm_switzerland", "rdm_switzerland"],
        }
    )
    assert request.sources == ["rdm_switzerland"]

    record = {
        "id": "907278",
        "title": "Development & Test Engineer R&D",
        "location": "Wetzikon, Switzerland",
        "url": job_url(DEVELOPMENT_SLUG),
        "detail": {
            "title": "Development & Test Engineer R&D",
            "location": "Wetzikon, Switzerland",
            "employment_type": "Full-time",
            "description": "Develop and test connectivity products.",
            "apply_url": job_url(DEVELOPMENT_SLUG),
        },
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="rdm_switzerland-907278",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "R&M Switzerland import"
    assert stored["company"] == "Reichle & De-Massari AG"


def test_rdm_reads_complete_public_catalog_without_browser() -> None:
    import httpx

    cards = [
        vacancy_card("swiss-role", "Swiss Role"),
        vacancy_card("foreign-role", "Foreign Role", location="Sofia, Bulgaria"),
    ]
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/career/jobs/":
            assert not request.url.query
            return httpx.Response(200, text=listing_html(cards, global_total=2))
        return httpx.Response(503)

    result = RdmSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Swiss Role"
    assert result.jobs[0].raw["detail_error"]
    assert len(requests) == 2
