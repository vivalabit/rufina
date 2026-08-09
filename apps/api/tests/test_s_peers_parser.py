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
from app.services.parsers.companies.s_peers import SPeersJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(*, job_id: str, slug: str, title: str, teaser: str) -> str:
    return f"""
    <div class="post-column content-grid-wrap">
      <div id="post-{job_id}"
           class="entry-post post-grid post-{job_id} job type-job status-publish hentry">
        <div class="entry-content">
          <div class="post-title">
            <a href="https://s-peers.test/job/{slug}/"><h3>{title}</h3></a>
          </div>
          <div class="post-grid-excerpt"><p>{teaser}</p></div>
        </div>
      </div>
    </div>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><body>
      <div class="elementor-widget-speers-post-list">
        <div class="content-grid-container">{"".join(cards)}</div>
      </div>
    </body></html>
    """


def detail_html(*, job_id: str, title: str, slug: str) -> str:
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "url": f"https://s-peers.test/job/{slug}/",
                "datePublished": "2026-08-01T07:35:27+00:00",
            },
            {"@type": "Organization", "name": "s-peers AG"},
        ],
    }
    return f"""
    <html><head>
      <link rel="canonical" href="https://s-peers.test/job/{slug}/">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <div data-elementor-type="single-post"
           class="elementor elementor-location-single post-{job_id} job type-job status-publish">
        <h1 class="elementor-heading-title">{title}</h1>
        <div data-elementor-type="wp-post" data-elementor-id="{job_id}"
             data-elementor-post-type="job">
          <div class="elementor-widget-text-editor">
            <div class="elementor-widget-container">
              <p>Build reliable analytics platforms.</p>
            </div>
          </div>
          <div class="elementor-widget-text-editor">
            <div class="elementor-widget-container">
              <h3>Deine Aufgaben:</h3>
              <ul><li>Develop data pipelines.</li><li>Support customers.</li></ul>
            </div>
          </div>
          <div class="elementor-widget-text-editor">
            <div class="elementor-widget-container">
              <p>Bitte achte darauf, alle Formularfelder auszufüllen.</p>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """


def test_s_peers_scans_and_enriches_complete_catalog() -> None:
    cards = [
        listing_card(
            job_id="48262",
            slug="senior-data-engineer",
            title="Senior Data Engineer (M/W/D)",
            teaser="Design modern data platforms.",
        ),
        listing_card(
            job_id="48257",
            slug="python-software-engineer",
            title="Python Software Engineer 80-100% (M/W/D)",
            teaser="Develop analytics software.",
        ),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/karriere-jobs/stellenausschreibungen/":
            return httpx.Response(200, text=listing_html(cards))
        if request.url.path == "/job/senior-data-engineer/":
            return httpx.Response(
                200,
                text=detail_html(
                    job_id="48262",
                    title="Senior Data Engineer (M/W/D)",
                    slug="senior-data-engineer",
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                job_id="48257",
                title="Python Software Engineer 80-100% (M/W/D)",
                slug="python-software-engineer",
            ),
        )

    parser = SPeersJobsParser(
        base_url="https://s-peers.test/karriere-jobs/stellenausschreibungen/",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 2 s-peers vacancies from the full catalog page"
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "s_peers"
    assert first.title == "Senior Data Engineer (M/W/D)"
    assert first.company == "s-peers AG"
    assert first.location == "Switzerland"
    assert first.url == "https://s-peers.test/job/senior-data-engineer/"
    assert first.apply_url == first.url
    assert first.posted_at == "2026-08-01T07:35:27+00:00"
    assert first.description == (
        "Build reliable analytics platforms.\n\n"
        "Deine Aufgaben:\n\n"
        "- Develop data pipelines.\n"
        "- Support customers."
    )
    assert first.raw["id"] == "48262"
    assert first.raw["detail"]["id"] == "48262"
    assert result.jobs[1].employment_type == "80%-100%"


def test_s_peers_preserves_listing_when_detail_request_fails() -> None:
    card = listing_card(
        job_id="48262",
        slug="senior-data-engineer",
        title="Senior Data Engineer (M/W/D)",
        teaser="Design modern data platforms.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere-jobs/stellenausschreibungen/":
            return httpx.Response(200, text=listing_html([card]))
        return httpx.Response(503, text="temporarily unavailable")

    parser = SPeersJobsParser(
        base_url="https://s-peers.test/karriere-jobs/stellenausschreibungen/",
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Senior Data Engineer (M/W/D)"
    assert job.description == "Design modern data platforms."
    assert job.apply_url == job.url
    assert job.posted_at is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_s_peers_rejects_listing_without_catalog_contract() -> None:
    parser = SPeersJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        parser.search(LinkedInSearchRequest())


def test_s_peers_rejects_incomplete_catalog() -> None:
    page = listing_html(
        [
            """
            <div id="post-48262" class="entry-post job type-job status-publish">
              <div class="post-title"><a href="/job/data-engineer/"></a></div>
            </div>
            """
        ]
    )
    parser = SPeersJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_s_peers_wraps_listing_request_failures() -> None:
    parser = SPeersJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_s_peers_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["s_peers"]
    assert isinstance(parser, SPeersJobsParser)
    assert parser.base_url == settings.s_peers_jobs_base_url
    assert parser.detail_workers == settings.s_peers_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "s-peers", "filters": {}},
            "sources": ["s_peers", "s_peers"],
        }
    )
    assert request.sources == ["s_peers"]


def test_s_peers_jobs_render_as_direct_company_imports() -> None:
    parser = SPeersJobsParser()
    job = parser.normalize_job(
        {
            "id": "48262",
            "title": "Senior Data Engineer (M/W/D)",
            "url": "https://s-peers.com/job/senior-data-engineer/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="s_peers-48262",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "s-peers import"
    assert stored["id"] == "s_peers-48262"
