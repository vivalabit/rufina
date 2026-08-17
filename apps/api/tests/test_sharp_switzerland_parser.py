from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.sharp_switzerland import (
    SharpSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOBS_URL = "https://www.sharp.ch/de/jobs-bei-sharp"
ACCOUNT_SLUG = "account-manager-mwd-region-romandie-unterwallis-100-ab-sofort"
SUPPORT_SLUG = "it-remote-support-specialist-wmd-ruchlikon-koniz-100-ab-sofort"


def job_url(slug: str) -> str:
    return f"https://www.sharp.ch/de/{slug}"


def vacancy_link(slug: str, title: str, *, host: str = "www.sharp.ch") -> str:
    return f'<p><a href="https://{host}/de/{slug}">{title}</a></p>'


def listing_html(
    links: str,
    *,
    canonical: str = JOBS_URL,
    apply_email: str = "HR.SEZ@sharp.eu",
    heading: str = "Jobs bei Sharp",
    catalog_heading: str = "Karriere bei Sharp",
    empty_text: str = "",
) -> str:
    return f"""
    <html lang="de-ch"><head>
      <link rel="canonical" href="{canonical}" />
      <meta property="og:title" content="{heading}" />
    </head><body><main>
      <div class="shp-hero__content"><h1 class="h2">{heading}</h1></div>
      <div class="shp-full-width-text">
        <h3>{catalog_heading}</h3>
        <div class="shp-content-wysiwyg">
          <p><strong>Offene Stellen</strong></p>
          <p>{empty_text or "Aktuell sind folgende Stellen zu besetzen:"}</p>
          {links}
          <p>Bewerbungen an <a href="mailto:{apply_email}">{apply_email}</a>.</p>
        </div>
      </div>
    </main></body></html>
    """


def detail_html(
    *,
    slug: str,
    title: str,
    metadata_title: str,
    summary: str,
    apply_email: str = "hr.sez@sharp.eu",
    profile_heading: str = "Ihr Profil",
) -> str:
    return f"""
    <html lang="de-ch"><head>
      <link rel="canonical" href="{job_url(slug)}" />
      <meta property="og:title" content="{metadata_title}" />
      <meta name="dcterms.title" content="{metadata_title}" />
    </head><body><main><article>
      <div class="shp-hero__content">
        <h1>{title}</h1><p>{summary}</p>
      </div>
      <div class="shp-landing-page__content">
        <section class="shp-text-media__text-block">
          <h2>Ihre Aufgaben</h2>
          <div class="shp-content-wysiwyg"><ul><li>Kunden beraten</li></ul></div>
        </section>
        <section class="shp-text-media__text-block">
          <h2>{profile_heading}</h2>
          <div class="shp-content-wysiwyg"><ul><li>Technische Erfahrung</li></ul></div>
        </section>
        <section class="shp-text-media__text-block">
          <h2>Unser Angebot</h2>
          <div class="shp-content-wysiwyg"><ul><li>Flexwork und fünf Wochen Ferien</li></ul></div>
          <a href="mailto:{apply_email}">Jetzt bewerben</a>
        </section>
      </div>
    </article></main></body></html>
    """


def official_links() -> str:
    return "".join(
        [
            vacancy_link(
                ACCOUNT_SLUG,
                "Account Manager (w/m/d), Region Romandie, Unterwallis |100 % | ab sofort",
            ),
            vacancy_link(
                SUPPORT_SLUG,
                "IT Remote Support Specialist (w/m/d), Rüchlikon, Köniz |100 % | ab sofort",
            ),
        ]
    )


def test_sharp_collects_complete_catalog_and_verified_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/de/jobs-bei-sharp":
            return httpx.Response(200, text=listing_html(official_links()))
        if request.url.path.endswith(ACCOUNT_SLUG):
            return httpx.Response(
                200,
                text=detail_html(
                    slug=ACCOUNT_SLUG,
                    title="Account Manager (m/w/d)",
                    metadata_title=(
                        "Account Manager (m/w/d) – Region Romandie, Unterwallis |100 % | ab sofort"
                    ),
                    summary="Region Romandie, Unterwallis |100 % | ab sofort",
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                slug=SUPPORT_SLUG,
                title="IT Remote Support Specialist (w/m/d)",
                metadata_title=(
                    "IT Remote Support Specialist (w/m/d) – Rüchlikon, Köniz |100 % | ab sofort"
                ),
                summary="Rüchlikon, Köniz |100 % | ab sofort",
            ),
        )

    result = SharpSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.message == (
        "Scanned 2 Sharp Switzerland vacancies from the complete official careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "sharp_switzerland"
    assert first.title == "Account Manager (m/w/d)"
    assert first.company == "Sharp Electronics (Schweiz) AG"
    assert first.location == "Region Romandie, Unterwallis, Switzerland"
    assert first.url == job_url(ACCOUNT_SLUG)
    assert first.apply_url == "mailto:hr.sez@sharp.eu"
    assert first.employment_type == "100 %"
    assert first.description == (
        "Ihre Aufgaben\nKunden beraten\n"
        "Ihr Profil\nTechnische Erfahrung\n"
        "Unser Angebot\nFlexwork und fünf Wochen Ferien"
    )
    assert first.raw["id"] == ACCOUNT_SLUG
    assert first.raw["detail"]["starts_at"] == "ab sofort"


def test_sharp_preserves_verified_listing_when_detail_fails() -> None:
    link = vacancy_link(ACCOUNT_SLUG, "Account Manager (w/m/d), Romandie")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs-bei-sharp":
            return httpx.Response(200, text=listing_html(link))
        return httpx.Response(503, text="unavailable")

    job = (
        SharpSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Account Manager (w/m/d), Romandie"
    assert job.location == "Switzerland"
    assert job.apply_url == "mailto:hr.sez@sharp.eu"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "message"),
    [
        (listing_html(official_links(), heading="Generic careers"), "unexpected identity"),
        (
            listing_html(official_links(), catalog_heading="Work with us"),
            "missing its vacancy catalog",
        ),
        (
            listing_html(vacancy_link(ACCOUNT_SLUG, "Account Manager", host="attacker.example")),
            "invalid vacancy link",
        ),
        (
            listing_html(official_links(), apply_email="attacker@example.com"),
            "application email",
        ),
    ],
)
def test_sharp_rejects_malformed_or_untrusted_catalogs(
    page_html: str,
    message: str,
) -> None:
    parser = SharpSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page_html))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_sharp_rejects_duplicate_and_oversized_catalogs() -> None:
    link = vacancy_link(ACCOUNT_SLUG, "Account Manager")
    duplicate = SharpSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html(link + link)))
    )
    oversized = SharpSwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(official_links()))
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_sharp_rejects_invalid_detail_but_keeps_listing() -> None:
    link = vacancy_link(ACCOUNT_SLUG, "Account Manager (w/m/d), Romandie")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs-bei-sharp":
            return httpx.Response(200, text=listing_html(link))
        return httpx.Response(
            200,
            text=detail_html(
                slug=ACCOUNT_SLUG,
                title="Different vacancy",
                metadata_title="Different vacancy",
                summary="Romandie |100 % | ab sofort",
            ),
        )

    job = (
        SharpSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == "mailto:hr.sez@sharp.eu"
    assert "different vacancy title" in str(job.raw["detail_error"])


def test_sharp_accepts_explicit_empty_catalog() -> None:
    page = listing_html("", empty_text="Aktuell sind keine offenen Stellen verfügbar.")
    result = SharpSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    ).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 Sharp Switzerland vacancies")


def test_sharp_wraps_listing_request_failures() -> None:
    parser = SharpSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_sharp_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["sharp_switzerland"]

    assert isinstance(parser, SharpSwitzerlandJobsParser)
    assert parser.base_url == settings.sharp_switzerland_jobs_base_url
    assert parser.max_jobs == settings.sharp_switzerland_jobs_max_jobs
    assert parser.detail_workers == settings.sharp_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Sharp Switzerland", "filters": {}},
            "sources": ["sharp_switzerland", "sharp_switzerland"],
        }
    )
    assert request.sources == ["sharp_switzerland"]

    record = {
        "id": ACCOUNT_SLUG,
        "title": "Account Manager (w/m/d)",
        "url": job_url(ACCOUNT_SLUG),
        "detail": {
            "title": "Account Manager (w/m/d)",
            "location": "Romandie, Switzerland",
            "workload": "100 %",
            "apply_url": "mailto:hr.sez@sharp.eu",
            "description": "Kunden beraten.",
        },
    }
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id=f"sharp_switzerland-{ACCOUNT_SLUG}",
        added_at=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Sharp Switzerland import"
    assert stored["company"] == "Sharp Electronics (Schweiz) AG"
