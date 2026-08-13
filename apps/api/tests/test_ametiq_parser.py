from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.ametiq import AmetiqJobsParser, parse_detail_html
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://ametiq.test/jobs/"


def page_head(page_url: str, *, site_name: str = "amétiq medical") -> str:
    return f"""
    <head>
      <meta property="og:site_name" content="{site_name}">
      <link rel="canonical" href="{page_url}">
    </head>
    """


def listing_card(*, post_id: str, slug: str, title: str) -> str:
    return f"""
    <div class="uael-post-wrapper">
      <h3 class="uael-post__title">amétiq medical &#8211; {title}</h3>
      <a class="uael-post__read-more" href="https://ametiq.test/job/{slug}/"
         aria-labelledby="uael-post-{post_id}">
        <span class="elementor-button-text" id="uael-post-{post_id}">Mehr</span>
      </a>
    </div>
    """


def listing_html(cards: list[str], *, site_name: str = "amétiq medical") -> str:
    return f"""
    <html lang="de-CH">
      {page_head(BASE_URL, site_name=site_name)}
      <body>
        <div id="open-jobs"><h2>Unsere Stellenangebote</h2></div>
        <div class="elementor-widget-uael-posts">
          <div class="uael-post-grid__inner">{"".join(cards)}</div>
        </div>
      </body>
    </html>
    """


def detail_html(
    *,
    post_id: str,
    slug: str,
    title: str,
    published_at: str = "2026-07-27T12:55:26+00:00",
    site_name: str = "amétiq medical",
    apply_url: str = "mailto:bewerbungen@ametiq.ch",
) -> str:
    page_url = f"https://ametiq.test/job/{slug}/"
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "url": page_url,
                "inLanguage": "de-CH",
                "datePublished": published_at,
            },
            {"@type": "Organization", "name": "amétiq ag"},
        ],
    }
    return f"""
    <html lang="de-CH">
      {page_head(page_url, site_name=site_name)}
      <head><script type="application/ld+json" class="yoast-schema-graph">
        {json.dumps(schema)}
      </script></head>
      <body class="single-job postid-{post_id}">
        <div class="elementor-widget-theme-post-title">
          <h1>amétiq medical &#8211; {title}</h1>
        </div>
        <div class="elementor-widget-theme-post-content">
          <div class="elementor-widget-container">
            <p>Wir entwickeln die modernste Schweizer Praxissoftware.</p>
            <h4>Deine Aufgaben</h4>
            <ul><li>Gestalte sichere digitale Lösungen.</li></ul>
            <h4>Dein Profil</h4>
            <ul><li>Du bringst fundierte IT-Erfahrung mit.</li></ul>
            <p>Bitte sende Deine Bewerbung an
              <a href="{apply_url}">bewerbungen@ametiq.ch</a>
            </p>
            <p>amétiq ag<br>bahnhofstrasse 1<br>8808 pfäffikon sz</p>
          </div>
        </div>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            post_id="13617",
            slug="ametiq-medical-it-solution-und-security-architektin-100",
            title="IT-Solution und Security Architekt:in 100%",
        ),
        listing_card(
            post_id="13431",
            slug="ametiq-medical-kundenberaterin-80-100",
            title="Kundenberater:in 80-100%",
        ),
        listing_card(
            post_id="12562",
            slug="lehrstelle-bei-ametiq-als-ict-fachfrau-ict-fachmann",
            title="Lehrstelle als ICT Fachfrau / ICT Fachmann 2027",
        ),
    ]


def test_ametiq_collects_complete_catalog_and_enriches_jobs() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/jobs/":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        record = {
            "/job/ametiq-medical-it-solution-und-security-architektin-100/": (
                "13617",
                "IT-Solution und Security Architekt:in 100%",
            ),
            "/job/ametiq-medical-kundenberaterin-80-100/": (
                "13431",
                "Kundenberater:in 80-100%",
            ),
            "/job/lehrstelle-bei-ametiq-als-ict-fachfrau-ict-fachmann/": (
                "12562",
                "Lehrstelle als ICT Fachfrau / ICT Fachmann 2027",
            ),
        }[request.url.path]
        return httpx.Response(
            200,
            text=detail_html(
                post_id=record[0],
                slug=request.url.path.strip("/").split("/")[-1],
                title=record[1],
            ),
            request=request,
        )

    result = AmetiqJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/jobs/",
        "/job/ametiq-medical-it-solution-und-security-architektin-100/",
        "/job/ametiq-medical-kundenberaterin-80-100/",
        "/job/lehrstelle-bei-ametiq-als-ict-fachfrau-ict-fachmann/",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 3 amétiq Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "ametiq"
    assert first.title == "IT-Solution und Security Architekt:in 100%"
    assert first.company == "amétiq ag"
    assert first.location == "Pfäffikon SZ, Switzerland"
    assert first.url == (
        "https://ametiq.test/job/ametiq-medical-it-solution-und-security-architektin-100/"
    )
    assert first.apply_url == "mailto:bewerbungen@ametiq.ch"
    assert first.posted_at == "2026-07-27T12:55:26+00:00"
    assert first.employment_type == "100%"
    assert first.description and "Deine Aufgaben" in first.description
    assert first.description and "- Gestalte sichere digitale Lösungen" in first.description
    assert first.raw["id"] == "13617"
    assert result.jobs[1].employment_type == "80–100%"
    assert result.jobs[2].employment_type is None


def test_ametiq_preserves_listing_when_detail_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs/":
            return httpx.Response(200, text=listing_html([card]), request=request)
        return httpx.Response(503, request=request)

    job = (
        AmetiqJobsParser(base_url=BASE_URL, transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "IT-Solution und Security Architekt:in 100%"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ametiq_rejects_incomplete_or_duplicate_catalog() -> None:
    card = catalog_fixture()[0]

    def parser_for(cards: list[str]) -> AmetiqJobsParser:
        return AmetiqJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(cards),
                    request=request,
                )
            ),
        )

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        parser_for([]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([card, card]).search(LinkedInSearchRequest())


def test_ametiq_rejects_wrong_identity_or_detail_contract() -> None:
    wrong_identity = AmetiqJobsParser(
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

    detail_url = "https://ametiq.test/job/ametiq-medical-kundenberaterin-80-100/"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                post_id="13431",
                slug="ametiq-medical-kundenberaterin-80-100",
                title="Kundenberater:in 80-100%",
                apply_url="mailto:attacker@example.com",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="13431",
            expected_title="Kundenberater:in 80-100%",
        )


def test_ametiq_accepts_the_official_apprenticeship_email() -> None:
    detail_url = "https://ametiq.test/job/lehrstelle-bei-ametiq-als-ict-fachfrau-ict-fachmann/"
    detail = parse_detail_html(
        detail_html(
            post_id="12562",
            slug="lehrstelle-bei-ametiq-als-ict-fachfrau-ict-fachmann",
            title="Lehrstelle als ICT Fachfrau / ICT Fachmann 2027",
            apply_url="mailto:lehrstellen@ametiq.ch",
        ),
        page_url=detail_url,
        expected_url=detail_url,
        expected_job_id="12562",
        expected_title="Lehrstelle als ICT Fachfrau / ICT Fachmann 2027",
    )

    assert detail["apply_url"] == "mailto:lehrstellen@ametiq.ch"


def test_ametiq_wraps_listing_request_failures() -> None:
    parser = AmetiqJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_ametiq_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ametiq"]
    assert isinstance(parser, AmetiqJobsParser)
    assert parser.base_url == settings.ametiq_jobs_base_url
    assert parser.detail_workers == settings.ametiq_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "amétiq", "filters": {}},
            "sources": ["ametiq", "ametiq"],
        }
    )
    assert request.sources == ["ametiq"]


def test_ametiq_jobs_render_as_direct_company_imports() -> None:
    job = AmetiqJobsParser().normalize_job(
        {
            "id": "13617",
            "title": "IT-Solution und Security Architekt:in 100%",
            "url": (
                "https://ametiq.ch/job/ametiq-medical-it-solution-und-security-architektin-100/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="ametiq-13617",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "amétiq ag import"
    assert stored["id"] == "ametiq-13617"
