from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.abraxas import (
    AbraxasJobsParser,
    parse_detail_html,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.abraxas.test/de/karriere/offene-stellen"
APPLY_URL = "https://apply.refline.ch/215876/2383/index.html?lang=de&cid=1"


def page_head(page_url: str, *, company: str = "Abraxas Informatik AG") -> str:
    return f"""
    <head>
      <meta property="og:site_name" content="{company}">
      <meta property="og:url" content="{page_url}">
    </head>
    """


def listing_card(
    job_id: str,
    *,
    slug: str,
    title: str,
    location: str,
    href: str | None = None,
) -> str:
    return f"""
    <li class="job-list__list-item" data-locations="4,5" data-positions="7">
      <a class="job-list__job"
         href="{href or f"/de/karriere/offene-stellen/{slug}-{job_id}"}">
        <div class="job-list__job-title">{title}</div>
        <div class="job-list__job-location">{location}</div>
        <div class="job-list__job-cta">Zur Stellenanzeige</div>
      </a>
    </li>
    """


def listing_html(cards: list[str], *, company: str = "Abraxas Informatik AG") -> str:
    return f"""
    <html lang="de">
      {page_head(BASE_URL, company=company)}
      <body><main><ul class="job-list__list">{"".join(cards)}</ul></main></body>
    </html>
    """


def detail_html(
    job_id: str,
    *,
    slug: str,
    title: str,
    location: str,
    workload: str = "80 - 100%",
    contract: str = "Festanstellung",
    apply_url: str = APPLY_URL,
    page_url: str | None = None,
) -> str:
    detail_url = page_url or f"{BASE_URL}/{slug}-{job_id}"
    return f"""
    <html lang="de">
      {page_head(detail_url)}
      <body>
        <header>
          <h1 class="header__title">{title}<span class="subtitle">{location}</span></h1>
          <a class="c-cta--secondary desktop" href="{apply_url}">Jetzt bewerben</a>
        </header>
        <main class="r-main">
          <section class="u-section">
            <ul class="definition-list__list">
              <li><div class="definition-list__item">
                <div class="definition-list__term">Pensum</div>
                <div class="desfinition-list__description">{workload}</div>
              </div></li>
              <li><div class="definition-list__item">
                <div class="definition-list__term">Anstellung</div>
                <div class="desfinition-list__description">{contract}</div>
              </div></li>
              <li><div class="definition-list__item">
                <div class="definition-list__term">Standort</div>
                <div class="desfinition-list__description">{location}</div>
              </div></li>
            </ul>
            <div class="c-rich-text--default">
              <div class="rich-text-field">
                <div class="rich-text__lead">Gestalte die digitale Schweiz mit uns.</div>
                <h2>Deine Rolle</h2>
                <ul><li>Entwickle zuverlässige Plattformen.</li><li>Arbeite im Team.</li></ul>
                <h2>Dein Profil</h2>
                <p>Du bringst Erfahrung im Software Engineering mit.</p>
              </div>
            </div>
          </section>
        </main>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "9876",
            slug="cyber-security-analyst-engineer-80-100",
            title="Cyber Security Analyst / Engineer 80–100 %",
            location="Zürich-Flughafen",
        ),
        listing_card(
            "3478",
            slug="ict-system-engineer-betrieb-80-100",
            title="ICT-System Engineer Betrieb 80–100 %",
            location="Kloten, St. Gallen",
        ),
    ]


def test_abraxas_collects_complete_catalog_and_enriches_every_vacancy() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/de/karriere/offene-stellen":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        if request.url.path.endswith("-9876"):
            return httpx.Response(
                200,
                text=detail_html(
                    "9876",
                    slug="cyber-security-analyst-engineer-80-100",
                    title="Cyber Security Analyst / Engineer 80–100 %",
                    location="Zürich-Flughafen",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                "3478",
                slug="ict-system-engineer-betrieb-80-100",
                title="ICT-System Engineer Betrieb 80–100 %",
                location="Kloten, St. Gallen",
                workload="100%",
            ),
            request=request,
        )

    result = AbraxasJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/de/karriere/offene-stellen",
        "/de/karriere/offene-stellen/cyber-security-analyst-engineer-80-100-9876",
        "/de/karriere/offene-stellen/ict-system-engineer-betrieb-80-100-3478",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Abraxas Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "abraxas"
    assert first.title == "Cyber Security Analyst / Engineer 80–100 %"
    assert first.company == "Abraxas Informatik AG"
    assert first.location == "Zürich-Flughafen, Switzerland"
    assert first.url == (
        "https://www.abraxas.test/de/karriere/offene-stellen/"
        "cyber-security-analyst-engineer-80-100-9876"
    )
    assert first.apply_url == APPLY_URL
    assert first.posted_at is None
    assert first.employment_type == "Festanstellung · 80–100%"
    assert first.description and "Gestalte die digitale Schweiz" in first.description
    assert first.description and "- Entwickle zuverlässige Plattformen" in first.description
    assert first.raw["detail"]["refline_job_id"] == "2383"
    assert result.jobs[1].location == "Kloten, St. Gallen, Switzerland"
    assert result.jobs[1].employment_type == "Festanstellung · 100%"


def test_abraxas_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/karriere/offene-stellen":
            return httpx.Response(
                200,
                text=listing_html([catalog_fixture()[0]]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        AbraxasJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Cyber Security Analyst / Engineer 80–100 %"
    assert job.location == "Zürich-Flughafen, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_abraxas_rejects_duplicate_unsafe_or_non_swiss_catalog_records() -> None:
    card = catalog_fixture()[0]

    def parser_for(cards: list[str]) -> AbraxasJobsParser:
        return AbraxasJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(cards),
                    request=request,
                )
            ),
        )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([card, card]).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(
            [
                listing_card(
                    "9876",
                    slug="cyber-security-analyst-engineer-80-100",
                    title="Cyber Security Analyst / Engineer 80–100 %",
                    location="Zürich-Flughafen",
                    href="https://attacker.example/de/karriere/offene-stellen/engineer-9876",
                )
            ]
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(
            [
                listing_card(
                    "9876",
                    slug="cyber-security-analyst-engineer-80-100",
                    title="Cyber Security Analyst / Engineer 80–100 %",
                    location="Paris",
                )
            ]
        ).search(LinkedInSearchRequest())


def test_abraxas_rejects_wrong_identity_or_detail_contract() -> None:
    wrong_identity = AbraxasJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), company="Other AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())

    detail_url = f"{BASE_URL}/cyber-security-analyst-engineer-80-100-9876"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "9876",
                slug="cyber-security-analyst-engineer-80-100",
                title="Cyber Security Analyst / Engineer 80–100 %",
                location="Zürich-Flughafen",
                apply_url=("https://attacker.example/215876/2383/index.html?lang=de&cid=1"),
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="9876",
            expected_title="Cyber Security Analyst / Engineer 80–100 %",
            expected_location="Zürich-Flughafen, Switzerland",
        )


def test_abraxas_wraps_listing_request_failures() -> None:
    parser = AbraxasJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_abraxas_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["abraxas"]
    assert isinstance(parser, AbraxasJobsParser)
    assert parser.base_url == settings.abraxas_jobs_base_url
    assert parser.detail_workers == settings.abraxas_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Abraxas", "filters": {}},
            "sources": ["abraxas", "abraxas"],
        }
    )
    assert request.sources == ["abraxas"]


def test_abraxas_jobs_render_as_direct_company_imports() -> None:
    job = AbraxasJobsParser().normalize_job(
        {
            "id": "9876",
            "title": "Cyber Security Analyst / Engineer 80–100 %",
            "location": "Zürich-Flughafen, Switzerland",
            "url": (
                "https://www.abraxas.ch/de/karriere/offene-stellen/"
                "cyber-security-analyst-engineer-80-100-9876"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="abraxas-9876",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Abraxas Informatik AG import"
    assert stored["id"] == "abraxas-9876"
