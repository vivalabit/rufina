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
from app.services.parsers.companies.helga import HelgaJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.helga.ch/jobs"
DRUPAL_SLUG = "senior-backend-developer-drupal"
PRODUCT_SLUG = "product-owner-digital-strategist"


def job_url(slug: str) -> str:
    return f"{BASE_URL}/{slug}"


def organization_schema(*, name: str = "Helga Digitalagentur", country: str = "CH") -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "name": name,
                    "address": {
                        "@type": "PostalAddress",
                        "addressCountry": country,
                    },
                }
            ],
        }
    )


def page_head(
    *,
    canonical: str,
    title: str,
    organization: str = "Helga Digitalagentur",
) -> str:
    return f"""
    <head>
      <link rel="canonical" href="{canonical}">
      <meta name="rights"
            content="Copyright ©2026 Helga Digitalagentur GmbH. All rights reserved.">
      <meta property="og:site_name" content="Helga Digitalagentur">
      <meta property="og:url" content="{canonical}">
      <meta property="og:title" content="{title}">
      <meta property="og:locality" content="Bern">
      <meta property="og:country_name" content="Schweiz">
      <script type="application/ld+json">
        {organization_schema(name=organization)}
      </script>
      <title>{title}</title>
    </head>
    """


def vacancy_card(
    *,
    slug: str,
    title: str,
    summary: str,
    location: str = "Bern, Länggasse",
    workload: str = "60–100%",
    salary: str | None = None,
) -> str:
    salary_item = f"<li>Lohnspanne: {salary}</li>" if salary else ""
    return f"""
    <div class="c-editor">
      <div class="c-editor__content">
        <h2><span>{title}</span></h2>
        <p>{summary}</p>
        <ul>
          <li><strong>Standort:</strong> {location}</li>
          <li>Stellenprozent: {workload}</li>
          {salary_item}
          <li><strong>Wann:</strong> Ab sofort – oder wann immer’s für dich passt</li>
        </ul>
      </div>
    </div>
    <div class="c-spacer"></div>
    <div class="c-call-to-action">
      <a class="c-button" href="/jobs/{slug}">Zur Stellenausschreibung</a>
    </div>
    """


def listing_html(
    cards: str,
    *,
    canonical: str = BASE_URL,
    apply_email: str = "jobs@helga.ch",
    marker: str = "Offene Stellen",
    organization: str = "Helga Digitalagentur",
) -> str:
    return f"""
    <html lang="de">
      {page_head(
          canonical=canonical,
          title="Werde Teil von Helga!",
          organization=organization,
      )}
      <body><main><article>
        <helga-section-title>{marker}</helga-section-title>
        {cards}
        <a href="mailto:{apply_email}">Bewerbung per E-Mail</a>
      </article></main></body>
    </html>
    """


def detail_html(
    *,
    slug: str,
    title: str,
    workload: str = "60–100%",
    apply_email: str = "jobs@helga.ch",
    canonical: str | None = None,
    organization: str = "Helga Digitalagentur",
) -> str:
    page_url = canonical or job_url(slug)
    return f"""
    <html lang="de">
      {page_head(
          canonical=page_url,
          title=f"Werde {title} bei Helga",
          organization=organization,
      )}
      <body><main><article>
        <h1 class="c-page-intro__title"><span>{title}</span></h1>
        <p class="c-page-intro__lead">
          Wir entwickeln digitale Lösungen, die Menschen begeistern.<br>
          Festanstellung vor Ort, {workload}, Länggasse Bern, ab sofort.
        </p>
        <a href="mailto:{apply_email}">Bewerbung an Felix</a>
        <helga-section-title>Deine Wirkung</helga-section-title>
        <h2>Was kann ich bewirken?</h2>
        <p>Du entwickelst nachhaltige digitale Produkte für unsere Kunden und
           bringst komplexe Projekte mit einem starken Team ins Ziel.</p>
        <helga-section-title>Über Helga</helga-section-title>
        <h2>Who the Hell is Helga?</h2>
        <p>Wir sind eine Berner Digitalagentur mit hohen Ansprüchen an
           Technologie, sauberen Code und eine nachhaltige Architektur.</p>
        <helga-section-title>Dein Profil</helga-section-title>
        <h2>Was sollte ich mitbringen?</h2>
        <p>Mehrjährige Erfahrung, klares Denken, strukturierte Arbeitsweise
           und Freude daran, Wissen im Team zu teilen.</p>
        <helga-section-title>Bewerbung</helga-section-title>
        <h2>Shut up and take my application!</h2>
        <p>Schick Felix deinen Lebenslauf, dein LinkedIn-Profil und passende
           Arbeitsproben. Dann liegt der Ball bei uns.</p>
        <a href="mailto:{apply_email}">Bewerbung an Felix</a>
      </article></main></body>
    </html>
    """


def official_cards() -> str:
    return "".join(
        [
            vacancy_card(
                slug=DRUPAL_SLUG,
                title="Senior Drupal Developer",
                summary=(
                    "Lieber Drupal-spezifische Herausforderungen als lange Meetings? "
                    "Wir bringen komplexe Drupal-Projekte gemeinsam auf den Boden."
                ),
            ),
            vacancy_card(
                slug=PRODUCT_SLUG,
                title="Product Owner & Digital Strategist",
                summary=(
                    "Du definierst mit unseren Kunden und dem UX-Team Lösungen, "
                    "Datenmodelle, User-Flows und klare Schnittstellen."
                ),
                salary="90–115k",
            ),
        ]
    )


def test_helga_scans_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(official_cards()), request=request)
        if request.url.path.endswith(DRUPAL_SLUG):
            return httpx.Response(
                200,
                text=detail_html(slug=DRUPAL_SLUG, title="Senior Drupal Developer"),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                slug=PRODUCT_SLUG,
                title="Product Owner & Digital Strategist",
            ),
            request=request,
        )

    result = HelgaJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [BASE_URL, job_url(DRUPAL_SLUG), job_url(PRODUCT_SLUG)]
    assert result.message == (
        "Scanned 2 Helga vacancies from the complete visible official careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "helga"
    assert first.title == "Senior Drupal Developer"
    assert first.company == "Helga Digitalagentur GmbH"
    assert first.location == "Bern, Länggasse, Switzerland"
    assert first.url == job_url(DRUPAL_SLUG)
    assert first.apply_url == "mailto:jobs@helga.ch"
    assert first.employment_type == "60–100%"
    assert first.description
    assert "Was kann ich bewirken?" in first.description
    assert "Was sollte ich mitbringen?" in first.description
    assert first.raw["catalog_index"] == 0
    assert first.raw["detail"]["metadata_title"] == (
        "Werde Senior Drupal Developer bei Helga"
    )
    assert result.jobs[1].raw["salary"] == "90–115k"


def test_helga_preserves_verified_listing_when_detail_fails() -> None:
    card = vacancy_card(
        slug=DRUPAL_SLUG,
        title="Senior Drupal Developer",
        summary="Wir entwickeln gemeinsam anspruchsvolle und nachhaltige Drupal-Projekte.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(card), request=request)
        return httpx.Response(503, request=request)

    job = (
        HelgaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Drupal Developer"
    assert job.location == "Bern, Länggasse, Switzerland"
    assert job.apply_url == "mailto:jobs@helga.ch"
    assert job.description == (
        "Wir entwickeln gemeinsam anspruchsvolle und nachhaltige Drupal-Projekte."
    )
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (
            listing_html(official_cards(), organization="Other Agency"),
            "unexpected identity",
        ),
        (listing_html(official_cards(), marker="Karriere"), "vacancy catalog"),
        (
            listing_html(official_cards(), apply_email="attacker@example.com"),
            "application email",
        ),
        (
            listing_html(
                vacancy_card(
                    slug=DRUPAL_SLUG,
                    title="Senior Drupal Developer",
                    summary="Wir entwickeln gemeinsam anspruchsvolle Drupal-Projekte in Bern.",
                    location="Berlin, Deutschland",
                )
            ),
            "incomplete vacancy card",
        ),
    ],
)
def test_helga_rejects_malformed_or_untrusted_catalogs(
    page_html: str,
    message: str,
) -> None:
    parser = HelgaJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page_html, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_helga_rejects_duplicate_and_oversized_catalogs() -> None:
    card = vacancy_card(
        slug=DRUPAL_SLUG,
        title="Senior Drupal Developer",
        summary="Wir entwickeln gemeinsam anspruchsvolle und nachhaltige Drupal-Projekte.",
    )
    duplicate = HelgaJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(card + card),
                request=request,
            )
        )
    )
    oversized = HelgaJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(official_cards()),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_helga_accepts_explicit_empty_catalog() -> None:
    result = HelgaJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(""),
                request=request,
            )
        )
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Helga vacancies from the complete visible official careers catalog"
    )


def test_helga_rejects_invalid_detail_but_keeps_listing() -> None:
    card = vacancy_card(
        slug=DRUPAL_SLUG,
        title="Senior Drupal Developer",
        summary="Wir entwickeln gemeinsam anspruchsvolle und nachhaltige Drupal-Projekte.",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(card), request=request)
        return httpx.Response(
            200,
            text=detail_html(
                slug=DRUPAL_SLUG,
                title="Different vacancy",
            ),
            request=request,
        )

    job = (
        HelgaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description.startswith("Wir entwickeln gemeinsam")
    assert "incomplete or inconsistent" in str(job.raw["detail_error"])


def test_helga_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["helga"]
    assert isinstance(parser, HelgaJobsParser)
    assert parser.base_url == settings.helga_jobs_base_url
    assert parser.max_jobs == settings.helga_jobs_max_jobs
    assert parser.detail_workers == settings.helga_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Helga", "filters": {}},
            "sources": ["helga", "helga"],
        }
    )
    assert request.sources == ["helga"]


def test_helga_jobs_render_as_direct_company_imports() -> None:
    job = HelgaJobsParser().normalize_job(
        {
            "id": DRUPAL_SLUG,
            "title": "Senior Drupal Developer",
            "location": "Bern, Länggasse",
            "workload": "60–100%",
            "url": job_url(DRUPAL_SLUG),
            "apply_url": "mailto:jobs@helga.ch",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"helga-{DRUPAL_SLUG}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Helga Digitalagentur import"
    assert stored["company"] == "Helga Digitalagentur GmbH"
    assert stored["id"] == f"helga-{DRUPAL_SLUG}"
