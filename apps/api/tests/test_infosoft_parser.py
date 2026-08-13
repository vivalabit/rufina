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
from app.services.parsers.companies.infosoft import InfosoftJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://infosoft.test/karriere/"


def page_head(page_url: str, *, site_name: str = "Infosoft Systems AG") -> str:
    return f"""
    <head>
      <link rel="canonical" href="{page_url}">
      <meta property="og:site_name" content="{site_name}">
    </head>
    """


def footer(*, city: str = "CH-6003 Luzern") -> str:
    return f"""
    <footer>
      <strong>Infosoft</strong>
      <span>Winkelriedstrasse 35</span><span>{city}</span>
    </footer>
    """


def listing_card(
    slug: str,
    *,
    title: str,
    workload: str = "90% bis 100%",
    summary: str = "Arbeite an moderner Software für den öffentlichen Verkehr.",
) -> str:
    return f"""
    <div class="tw-rounded-lg grid-card-box-shadow tw-bg-blue">
      <p>{title} &#8211; {workload} in Luzern</p>
      <p>{summary}</p>
      <a href="/karriere/{slug}/" class="link-with-arrow">zum Job Profil</a>
    </div>
    """


def listing_html(
    cards: list[str],
    *,
    site_name: str = "Infosoft Systems AG",
    city: str = "CH-6003 Luzern",
) -> str:
    return f"""
    <html lang="de-DE">
      {page_head(BASE_URL, site_name=site_name)}
      <body>
        <main>
          <section id="offene-stellen">
            <h3>Aktuell</h3><h2>offene Stellen</h2>
            <div class="tw-grid">{"".join(cards)}</div>
          </section>
          <section><h2>Wir bieten dir einen zeitgemässen Arbeitsplatz</h2></section>
        </main>
        {footer(city=city)}
      </body>
    </html>
    """


def detail_html(
    slug: str,
    *,
    title: str,
    workload: str = "90–100 %",
    published_at: str = "2026-03-30T12:43:31+00:00",
    apply_url: str = (
        "mailto:bewerbung@infosoft.swiss?subject=Bewerbung als Software Engineer/in .NET"
    ),
    city: str = "Luzern",
) -> str:
    detail_url = f"https://infosoft.test/karriere/{slug}/"
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "url": detail_url,
                "inLanguage": "de",
                "datePublished": published_at,
            },
            {"@type": "Organization", "name": "infosoft"},
        ],
    }
    return f"""
    <html lang="de-DE">
      {page_head(detail_url)}
      <head>
        <script type="application/ld+json" class="yoast-schema-graph">
          {json.dumps(schema)}
        </script>
      </head>
      <body>
        <main>
          <div class="reversed-photo-article">
            <article>
              <h4>{workload} | {city}</h4>
              <h3>{title}</h3>
              <p>Entwickle verlässliche Software für den öffentlichen Verkehr.</p>
            </article>
          </div>
          <article>
            <div>
              <h5>Das sind deine Aufgaben</h5>
              <p>• Konzeption und Entwicklung moderner .NET-Lösungen</p>
            </div>
            <div>
              <h5>Das bringst du mit</h5>
              <p>• Sehr gute Kenntnisse in .NET und C#</p>
            </div>
            <div>
              <h5>Wir bieten dir</h5>
              <p>Einen attraktiven Arbeitsplatz im Herzen von Luzern.</p>
            </div>
          </article>
          <section>
            <h4>Bewerbung</h4>
            <a href="{apply_url}">bewerbung@infosoft.swiss</a>
          </section>
        </main>
        {footer()}
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "senior-software-engineer-in-net",
            title="Senior Software Engineer .Net",
        ),
        listing_card(
            "ict-supporter-in",
            title="ICT Supporter",
            workload="80% bis 100%",
            summary="Unterstütze unsere Kunden und internen Teams.",
        ),
    ]


def test_infosoft_collects_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/karriere/":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        if request.url.path == "/karriere/senior-software-engineer-in-net/":
            return httpx.Response(
                200,
                text=detail_html(
                    "senior-software-engineer-in-net",
                    title="Senior Software Engineer/in .NET",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                "ict-supporter-in",
                title="ICT Supporter/in",
                workload="80–100 %",
                apply_url=(
                    "mailto:bewerbung@infosoft.swiss?subject="
                    "Bewerbung als ICT Supporter/in"
                ),
            ),
            request=request,
        )

    result = InfosoftJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/karriere/",
        "/karriere/senior-software-engineer-in-net/",
        "/karriere/ict-supporter-in/",
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Infosoft Switzerland vacancies from the official catalog"
    )
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "infosoft"
    assert first.title == "Senior Software Engineer/in .NET"
    assert first.company == "Infosoft Systems AG"
    assert first.location == "Luzern, Switzerland"
    assert first.url == (
        "https://infosoft.test/karriere/senior-software-engineer-in-net/"
    )
    assert first.apply_url == (
        "mailto:bewerbung@infosoft.swiss?subject="
        "Bewerbung als Software Engineer/in .NET"
    )
    assert first.posted_at == "2026-03-30T12:43:31+00:00"
    assert first.employment_type == "90–100%"
    assert first.description and "Das sind deine Aufgaben" in first.description
    assert first.description and "Sehr gute Kenntnisse" in first.description
    assert first.raw["id"] == "senior-software-engineer-in-net"
    assert result.jobs[1].employment_type == "80–100%"


def test_infosoft_preserves_listing_when_detail_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/":
            return httpx.Response(200, text=listing_html([card]), request=request)
        return httpx.Response(503, request=request)

    job = (
        InfosoftJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Software Engineer .Net"
    assert job.apply_url == job.url
    assert job.description and "öffentlichen Verkehr" in job.description
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_infosoft_rejects_incomplete_duplicate_or_non_swiss_catalog() -> None:
    card = catalog_fixture()[0]

    def run(page: str) -> None:
        InfosoftJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        run(listing_html([]))
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        run(listing_html([card, card]))
    with pytest.raises(DirectCompanyRequestError, match="Swiss company identity"):
        run(listing_html([card], city="D-10115 Berlin"))


def test_infosoft_rejects_wrong_identity_or_detail_contract() -> None:
    wrong_identity = InfosoftJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), site_name="Other AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())

    detail_url = "https://infosoft.test/karriere/senior-software-engineer-in-net/"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "senior-software-engineer-in-net",
                title="Senior Software Engineer/in .NET",
                apply_url="mailto:attacker@example.com?subject=Bewerbung als Engineer",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="senior-software-engineer-in-net",
            expected_title="Senior Software Engineer .Net",
            expected_workload="90–100%",
            expected_location="Luzern, Switzerland",
        )


def test_infosoft_wraps_listing_request_failures() -> None:
    parser = InfosoftJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_infosoft_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["infosoft"]
    assert isinstance(parser, InfosoftJobsParser)
    assert parser.base_url == settings.infosoft_jobs_base_url
    assert parser.detail_workers == settings.infosoft_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Infosoft", "filters": {}},
            "sources": ["infosoft", "infosoft"],
        }
    )
    assert request.sources == ["infosoft"]


def test_infosoft_jobs_render_as_direct_company_imports() -> None:
    job = InfosoftJobsParser().normalize_job(
        {
            "id": "senior-software-engineer-in-net",
            "title": "Senior Software Engineer .Net",
            "location": "Luzern, Switzerland",
            "employment_type": "90–100%",
            "url": (
                "https://infosoft.swiss/karriere/"
                "senior-software-engineer-in-net/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="infosoft-senior-software-engineer-in-net",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Infosoft Systems AG import"
    assert stored["id"] == "infosoft-senior-software-engineer-in-net"
