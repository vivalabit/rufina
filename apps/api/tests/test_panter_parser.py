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
from app.services.parsers.companies.panter import PanterJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.panter.ch/en/about-us/career/"
AI_URL = "https://www.panter.ch/ueber-uns/karriere/senior-ai-software-engineer/"
PRODUCT_URL = (
    "https://www.panter.ch/ueber-uns/karriere/senior-product-owner-requirements-engineer-senior/"
)


def listing_html() -> str:
    organization = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "legalName": "Panter AG",
                "url": "https://www.panter.ch/en/",
                "email": "hello@panter.ch",
                "telephone": "+41 44 500 29 04",
            }
        ],
    }
    cards = "".join(
        f"""
        <div class="nectar-hor-list-item">
          <h2>{title}</h2>
          <div class="nectar-list-item">Zürich / Remote, 60-100%</div>
          <div class="nectar-list-item">Learn more</div>
          <a class="full-link" href="{url}"></a>
        </div>
        """
        for title, url in (
            ("Senior AI Software Engineer", AI_URL),
            ("Senior Product Owner", PRODUCT_URL),
        )
    )
    return f"""
    <html lang="en-US"><head>
      <link rel="canonical" href="{BASE_URL}">
      <meta property="og:url" content="{BASE_URL}">
      <script type="application/ld+json">{json.dumps(organization)}</script>
    </head><body>
      <div id="logo"><img src="https://www.panter.ch/wp-content/uploads/panter-logo-black.svg"></div>
      {cards}
      <a href="mailto:jobs@panter.ch">jobs@panter.ch</a>
    </body></html>
    """


def detail_html(
    *,
    url: str,
    title: str,
    form_title: str,
    posted_at: str = "2026-07-17T09:06:29+00:00",
) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "url": url,
        "inLanguage": "de",
        "datePublished": posted_at,
    }
    action = f"{httpx.URL(url).path}?wpforms_form_id=12482"
    return f"""
    <html lang="de"><head>
      <meta property="og:url" content="{url}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <h1>{title}</h1>
      <p>Ab sofort oder nach Vereinbarung<br>Level: Senior<br>
        Pensum: 60-100%<br>Standort: Zürich, hybrid</p>
      <section id="panter"><h2>Panter</h2><p>Wir entwickeln digitale Produkte.</p></section>
      <section id="job"><h2>Deine Aufgaben</h2><ul><li>Du baust nachhaltige Lösungen.</li></ul></section>
      <section id="profil"><h2>Dein Profil</h2><p>Du bringst viel Erfahrung mit.</p></section>
      <section id="bewerben">
        <form class="wpforms-form" data-formid="12482" action="{action}">
          <input type="hidden" name="wpforms[fields][26]" value="{form_title}">
        </form>
      </section>
    </body></html>
    """


def parser_with_catalog(*, detail_status: int = 200) -> PanterJobsParser:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/about-us/career/":
            return httpx.Response(200, text=listing_html(), request=request)
        if detail_status != 200:
            return httpx.Response(detail_status, request=request)
        if request.url.path == httpx.URL(AI_URL).path:
            body = detail_html(
                url=AI_URL,
                title="Senior AI Software Engineer",
                form_title="Senior AI Software Engineer",
            )
        elif request.url.path == httpx.URL(PRODUCT_URL).path:
            body = detail_html(
                url=PRODUCT_URL,
                title="Senior Product Owner / Requirements Engineer",
                form_title="Senior Product Owner /  Requirements Engineer",
                posted_at="2026-07-17T09:09:50+00:00",
            )
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(200, text=body, request=request)

    return PanterJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )


def test_panter_collects_and_enriches_complete_catalog() -> None:
    result = parser_with_catalog().search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 Panter Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "panter"
    assert first.title == "Senior AI Software Engineer"
    assert first.company == "Panter AG"
    assert first.location == "8005 Zürich, Switzerland"
    assert first.posted_at == "2026-07-17"
    assert first.employment_type == "Part-time / Full-time · 60–100%"
    assert first.seniority == "Senior"
    assert "Du baust nachhaltige Lösungen." in (first.description or "")
    assert first.apply_url == f"{AI_URL}#bewerben"
    assert result.jobs[1].apply_url == f"{PRODUCT_URL}#bewerben"


def test_panter_preserves_catalog_when_details_fail() -> None:
    result = parser_with_catalog(detail_status=503).search(LinkedInSearchRequest())

    assert len(result.jobs) == 2
    assert all(job.apply_url == job.url for job in result.jobs)
    assert all(job.posted_at is None for job in result.jobs)
    assert all(job.description is None for job in result.jobs)
    assert all("503 Service Unavailable" in job.raw["detail_error"] for job in result.jobs)


def test_panter_rejects_wrong_identity_and_http_failures() -> None:
    parser = PanterJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<html><title>Lookalike careers</title></html>",
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    parser = PanterJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_panter_rejects_incomplete_catalog_card() -> None:
    broken = listing_html().replace("Zürich / Remote, 60-100%", "Zürich", 1)
    parser = PanterJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=broken, request=request)
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_panter_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["panter"]
    assert isinstance(parser, PanterJobsParser)
    assert parser.base_url == settings.panter_jobs_base_url
    assert parser.detail_workers == settings.panter_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Panter", "filters": {}},
            "sources": ["panter", "panter"],
        }
    )
    assert request.sources == ["panter"]

    job = normalize_job(
        {
            "id": "senior-ai-software-engineer",
            "title": "Senior AI Software Engineer",
            "location": "8005 Zürich, Switzerland",
            "workload": "60–100%",
            "url": AI_URL,
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="panter-senior-ai-software-engineer",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Panter AG import"
    assert stored["id"] == "panter-senior-ai-software-engineer"
