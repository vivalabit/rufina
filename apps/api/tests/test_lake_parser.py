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
from app.services.parsers.companies.lake import (
    LakeJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://lake.ch/ueber-uns/karriere"
SUPPORT_SLUG = "service-desk-support-engineer"
CONTROLLER_SLUG = "controller"


def job_url(slug: str) -> str:
    return f"{BASE_URL}/{slug}"


def page_head(
    *,
    canonical: str,
    title: str,
    site_name: str = "LAKE Solutions AG",
    schema: dict[str, object] | None = None,
) -> str:
    schema_html = (
        f'<script type="application/ld+json">{json.dumps(schema)}</script>'
        if schema
        else ""
    )
    return f"""
    <head>
      <title>{title}</title>
      <link rel="canonical" href="{canonical}">
      <meta property="og:site_name" content="{site_name}">
      {schema_html}
    </head>
    """


def listing_html(
    links: list[tuple[str, str]],
    *,
    site_name: str = "LAKE Solutions AG",
    listing_heading: str = "Offene Stellen bei LAKE",
    catalog_heading: str = "Derzeit offen",
) -> str:
    cards = "".join(
        f'<li><a href="{job_url(slug)}"><strong>{title}</strong></a></li>'
        for slug, title in links
    )
    return f"""
    <html lang="de">
      {page_head(canonical=BASE_URL, title="Karriere", site_name=site_name)}
      <body>
        <div class="text-image--text-container">
          <h2>{listing_heading}</h2>
          <p>Wir entwickeln hochwertige ICT-Lösungen für unsere Kunden.</p>
          <h3>{catalog_heading}</h3>
          <ul>{cards}</ul>
        </div>
      </body>
    </html>
    """


def detail_html(
    *,
    slug: str,
    title: str,
    canonical: str | None = None,
    site_name: str = "LAKE Solutions AG",
    company: str = "LAKE Solutions AG",
    apply_email: str = "job@lake.ch",
) -> str:
    public_url = canonical or job_url(slug)
    schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": title,
        "headline": title,
        "url": public_url,
        "datePublished": "2023-07-18T08:18:00+02:00",
        "dateModified": "2026-08-11T13:04:30+02:00",
    }
    return f"""
    <html lang="de">
      {page_head(
          canonical=public_url,
          title=title,
          site_name=site_name,
          schema=schema,
      )}
      <body>
        <div class="text-image--text-container">
          <h2>{title}</h2>
          <p>Zur Verstärkung unseres Teams suchen wir eine engagierte Person,
             die unsere Kunden zuverlässig betreut und moderne Lösungen
             gemeinsam mit erfahrenen Kolleginnen und Kollegen umsetzt.</p>
          <h2>Dein Aufgabengebiet</h2>
          <ul>
            <li>Du analysierst Anforderungen und entwickelst passende Lösungen.</li>
            <li>Du verantwortest den stabilen Betrieb und unterstützt Kunden.</li>
          </ul>
          <h2>Dein Profil</h2>
          <p>Du bringst fundierte ICT-Erfahrung, Eigeninitiative, sehr gute
             Deutschkenntnisse und Freude an der Zusammenarbeit mit.</p>
          <h2>Was wir Dir bieten</h2>
          <p>Flexible Arbeitszeiten, Homeoffice, Weiterbildungsmöglichkeiten,
             attraktive Sozialleistungen und ein motiviertes Team.</p>
          <p>{company}, Michèle Neuenschwander, Hertistrasse 2,
             8304 Wallisellen. E-Mail: {apply_email}</p>
          <p><a href="mailto:{apply_email}">Jetzt bewerben</a></p>
        </div>
      </body>
    </html>
    """


def official_links() -> list[tuple[str, str]]:
    return [
        (SUPPORT_SLUG, "Service Desk Support Engineer (m/w/d) 100%"),
        (CONTROLLER_SLUG, "Controller (m/w/d) 80-100%"),
    ]


def test_lake_scans_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/ueber-uns/karriere":
            return httpx.Response(
                200,
                text=listing_html(official_links()),
                request=request,
            )
        slug = request.url.path.rsplit("/", 1)[-1]
        title = dict(official_links())[slug]
        return httpx.Response(
            200,
            text=detail_html(slug=slug, title=title),
            request=request,
        )

    result = LakeJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/ueber-uns/karriere",
        f"/ueber-uns/karriere/{SUPPORT_SLUG}",
        f"/ueber-uns/karriere/{CONTROLLER_SLUG}",
    ]
    assert result.message == (
        "Scanned 2 Lake vacancies from the complete visible official careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "lake"
    assert first.title == "Service Desk Support Engineer (m/w/d) 100%"
    assert first.company == "LAKE Solutions AG"
    assert first.location == "Wallisellen, Switzerland"
    assert first.url == job_url(SUPPORT_SLUG)
    assert first.apply_url == "mailto:job@lake.ch"
    assert first.posted_at == "2023-07-18T08:18:00+02:00"
    assert first.employment_type == "100%"
    assert first.description and "Dein Aufgabengebiet" in first.description
    assert "- Du analysierst Anforderungen" in first.description
    assert first.raw["catalog_index"] == 0
    assert first.raw["detail"]["updated_at"] == "2026-08-11T13:04:30+02:00"
    assert result.jobs[1].employment_type == "80-100%"


def test_lake_preserves_verified_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ueber-uns/karriere":
            return httpx.Response(
                200,
                text=listing_html(official_links()[:1]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        LakeJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Service Desk Support Engineer (m/w/d) 100%"
    assert job.location == "Wallisellen, Switzerland"
    assert job.apply_url == "mailto:job@lake.ch"
    assert job.employment_type == "100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (listing_html(official_links(), site_name="Other AG"), "invalid identity"),
        (
            listing_html(official_links(), catalog_heading="Unsere Vorteile"),
            "vacancy catalog",
        ),
        (
            listing_html([(SUPPORT_SLUG, "")]),
            "incomplete vacancy",
        ),
    ],
)
def test_lake_rejects_malformed_or_untrusted_catalogs(
    body: str,
    message: str,
) -> None:
    parser = LakeJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_lake_rejects_duplicate_and_oversized_catalogs() -> None:
    duplicate = LakeJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([official_links()[0], official_links()[0]]),
                request=request,
            )
        )
    )
    oversized = LakeJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(official_links()),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        oversized.search(LinkedInSearchRequest())


def test_lake_rejects_untrusted_detail_page() -> None:
    title = "Service Desk Support Engineer (m/w/d) 100%"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                slug=SUPPORT_SLUG,
                title=title,
                company="Other AG",
                apply_email="jobs@attacker.example",
            ),
            page_url=job_url(SUPPORT_SLUG),
            expected_url=job_url(SUPPORT_SLUG),
            expected_title=title,
            expected_job_id=SUPPORT_SLUG,
        )

    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html(
                slug=SUPPORT_SLUG,
                title=title,
                canonical=job_url("another-role"),
            ),
            page_url=job_url("another-role"),
            expected_url=job_url(SUPPORT_SLUG),
            expected_title=title,
            expected_job_id=SUPPORT_SLUG,
        )


def test_lake_wraps_catalog_request_failures() -> None:
    parser = LakeJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_lake_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["lake"]
    assert isinstance(parser, LakeJobsParser)
    assert parser.base_url == settings.lake_jobs_base_url
    assert parser.max_jobs == settings.lake_jobs_max_jobs
    assert parser.detail_workers == settings.lake_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Lake", "filters": {}},
            "sources": ["lake", "lake"],
        }
    )
    assert request.sources == ["lake"]


def test_lake_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": SUPPORT_SLUG,
            "title": "Service Desk Support Engineer (m/w/d) 100%",
            "company": "LAKE Solutions AG",
            "location": "Wallisellen, Switzerland",
            "workload": "100%",
            "url": job_url(SUPPORT_SLUG),
            "apply_url": "mailto:job@lake.ch",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"lake-{SUPPORT_SLUG}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "LAKE Solutions AG import"
    assert stored["id"] == f"lake-{SUPPORT_SLUG}"
