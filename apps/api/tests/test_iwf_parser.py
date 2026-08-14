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
from app.services.parsers.companies.iwf import IwfJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.iwf.test/web-solutions/jobs"


def webpage_schema(page_url: str, *, title: str, published: str) -> str:
    payload = {
        "@context": "http://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "dateModified": "2026-08-07T15:03:16+02:00",
                "datePublished": published,
                "headline": title,
                "inLanguage": "de-ch",
                "mainEntityOfPage": page_url,
                "name": title,
                "url": page_url,
            },
            {"@id": "#identity", "@type": "Organization"},
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "item": "https://www.iwf.ch",
                        "name": "IWF AG - Full Service Agentur in Pratteln",
                        "position": 1,
                    },
                    {
                        "@type": "ListItem",
                        "item": page_url,
                        "name": title,
                        "position": 2,
                    },
                ],
            },
        ],
    }
    return json.dumps(payload)


def page_head(page_url: str, *, title: str) -> str:
    return f"""
    <head>
      <meta property="og:site_name" content="IWF AG">
      <meta property="og:url" content="{page_url}">
      <meta property="og:title" content="{title}">
      <link rel="canonical" href="{page_url}">
    </head>
    """


def header() -> str:
    return """
    <header>
      <img class="logo" src="/assets/content/logos/logo_iwf_ws.svg"
           alt="IWF Logo">
    </header>
    """


def footer(*, postcode: str = "CH-4133 Pratteln") -> str:
    return f"""
    <footer id="footer">
      <div class="footer-address">
        IWF AG<br>c/o Haus der Wirtschaft<br>Hardstrasse 1<br>{postcode}
      </div>
      <div>+41 61 927 64 76</div>
    </footer>
    """


def listing_card(slug: str, *, title: str) -> str:
    return f"""
    <div class="col-xs-12 col-sm-12 col-md-6 text-center inner-bottom-xs">
      <div class="teaser-image">
        <img class="teaser-image width-full" src="/{slug}.jpg" alt="{title}">
      </div>
      <div class="equalheight"><h3 class="color-ws">{title}</h3></div>
      <a href="/web-solutions/jobs/{slug}" class="btn btn-large bg-ws">
        Zum Job Profil
      </a>
    </div>
    """


def listing_html(
    cards: list[str],
    *,
    language: str = "de",
    postcode: str = "CH-4133 Pratteln",
) -> str:
    return f"""
    <html lang="{language}">
      {page_head(BASE_URL, title="Jobs")}
      <body>
        {header()}
        <main>
          <section id="main">
            <div class="container content inner-top-xs">
              <div class="row"><h1>Arbeiten bei der IWF Web Solutions</h1></div>
              <div class="row inner-top-xs">{"".join(cards)}</div>
            </div>
          </section>
        </main>
        {footer(postcode=postcode)}
        <script type="application/ld+json">
          {webpage_schema(BASE_URL, title="Jobs", published="2020-03-18T11:24:00+01:00")}
        </script>
      </body>
    </html>
    """


def detail_html(
    slug: str,
    *,
    hero_title: str,
    schema_title: str | None = None,
    email: str = "jobs@web-solutions.io",
) -> str:
    page_url = f"https://www.iwf.test/web-solutions/jobs/{slug}"
    canonical_title = schema_title or hero_title
    return f"""
    <html lang="de">
      {page_head(page_url, title=canonical_title)}
      <body>
        {header()}
        <main>
          <section id="hero"><h1>{hero_title}</h1></section>
          <div class="container inner-bottom-xs content">
            <p>Wir realisieren anspruchsvolle Software-Projekte.</p>
            <p><strong>Deine Aufgaben</strong></p>
            <ul><li>Entwickle nachhaltige Web-Lösungen.</li></ul>
            <p><strong>Dein Profil</strong></p>
            <ul><li>Sehr gute Deutschkenntnisse.</li></ul>
            <p>Sende deine Bewerbung an
              <a href="mailto:{email}">{email}</a>.
              <a href="mailto:s.marchetta@iwf.ch"></a>
            </p>
          </div>
        </main>
        {footer()}
        <script type="application/ld+json">
          {webpage_schema(page_url, title=canonical_title, published="2020-03-18T11:26:00+01:00")}
        </script>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "agile-tester",
            title="Agile Software Tester / Test Manager",
        ),
        listing_card(
            "full-stack-php-entwickler-in",
            title="Fullstack PHP/Web Entwickler/in",
        ),
    ]


def test_iwf_collects_complete_catalog_and_enriches_job_profiles() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/web-solutions/jobs":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        if request.url.path.endswith("/agile-tester"):
            return httpx.Response(
                200,
                text=detail_html(
                    "agile-tester",
                    hero_title="Agile Software Tester / Test Manager",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                "full-stack-php-entwickler-in",
                hero_title="Full-Stack Entwickler PHP/Symfony/React",
                schema_title="Full-Stack Entwickler/in PHP/Symfony/React",
            ),
            request=request,
        )

    result = IwfJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/web-solutions/jobs",
        "/web-solutions/jobs/agile-tester",
        "/web-solutions/jobs/full-stack-php-entwickler-in",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 IWF Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.source == "iwf"
    assert first.title == "Agile Software Tester / Test Manager"
    assert first.company == "IWF AG"
    assert first.location == "Pratteln, Switzerland"
    assert first.url == "https://www.iwf.test/web-solutions/jobs/agile-tester"
    assert first.apply_url == "mailto:jobs@web-solutions.io"
    assert first.posted_at == "2020-03-18"
    assert first.employment_type is None
    assert first.description and "nachhaltige Web-Lösungen" in first.description
    assert second.title == "Full-Stack Entwickler/in PHP/Symfony/React"
    assert second.raw["title"] == "Fullstack PHP/Web Entwickler/in"


def test_iwf_preserves_listing_when_detail_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/web-solutions/jobs":
            return httpx.Response(200, text=listing_html([card]), request=request)
        return httpx.Response(503, request=request)

    job = (
        IwfJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Agile Software Tester / Test Manager"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_iwf_rejects_missing_duplicate_or_changed_catalog() -> None:
    card = catalog_fixture()[0]

    def run(page: str) -> None:
        IwfJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        run(listing_html([]))
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        run(listing_html([card, card]))
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        run(listing_html([card], language="en"))
    with pytest.raises(DirectCompanyRequestError, match="Swiss company identity"):
        run(listing_html([card], postcode="D-10115 Berlin"))


def test_iwf_rejects_invalid_detail_contract() -> None:
    detail_url = "https://www.iwf.test/web-solutions/jobs/agile-tester"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "agile-tester",
                hero_title="Agile Software Tester / Test Manager",
                email="attacker@example.com",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="agile-tester",
        )


def test_iwf_wraps_listing_request_failures() -> None:
    parser = IwfJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_iwf_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["iwf"]
    assert isinstance(parser, IwfJobsParser)
    assert parser.base_url == settings.iwf_jobs_base_url
    assert parser.detail_workers == settings.iwf_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "iwf", "filters": {}}, "sources": ["iwf", "iwf"]}
    )
    assert request.sources == ["iwf"]

    job = parser.normalize_job(
        {
            "id": "agile-tester",
            "title": "Agile Software Tester / Test Manager",
            "url": "https://www.iwf.ch/web-solutions/jobs/agile-tester",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="iwf-agile-tester",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "IWF AG import"
    assert stored["id"] == "iwf-agile-tester"
