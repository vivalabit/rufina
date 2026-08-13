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
from app.services.parsers.companies.edorex import EdorexJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://edorex.test/jobs"
SENIOR_APPLY_URL = "https://link.ostendis.com/cvdropper/87ad8d9569a5473da808ae0b7cd4072b/DE"
APPRENTICE_APPLY_URL = (
    "https://odm.ostendis.com/ojp/#!/cvdropper/4b29543499dd4916974ee7014131fd6c/DE"
)


def listing_card(
    job_id: str,
    *,
    title: str,
    employment_type: str = "Vollzeit",
    location: str = "Ostermundigen",
    posted_label: str = "01.03.2026",
    href: str | None = None,
) -> str:
    return f"""
    <a href="{href or f"https://edorex.test/jobs/{job_id}"}">
      <h2>{title}</h2>
      <div class="mt-2">
        <span>{employment_type}</span>
        <span><svg></svg>{location}</span>
        <span>{posted_label}</span>
      </div>
      <p class="line-clamp-2">Kurze Zusammenfassung für {title}.</p>
    </a>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><body><main>
      <div class="space-y-6">{"".join(cards)}</div>
    </main></body></html>
    """


def detail_html(
    job_id: str,
    *,
    title: str,
    employment_type: str = "FULL_TIME",
    date_posted: str = "2026-03-01",
    apply_url: str = SENIOR_APPLY_URL,
    canonical_url: str | None = None,
    company_name: str = "Edorex AG",
) -> str:
    organization = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://edorex.ch#organization",
                "name": company_name,
                "url": "https://edorex.ch",
                "address": {
                    "@type": "PostalAddress",
                    "addressCountry": "CH",
                    "addressLocality": "Ostermundigen",
                },
            }
        ],
    }
    job = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": "Gekürzte strukturierte Beschreibung.",
        "datePosted": date_posted,
        "employmentType": employment_type,
        "jobLocation": {"@type": "Place", "address": "Ostermundigen"},
        "hiringOrganization": {"@id": "https://edorex.ch#organization"},
    }
    canonical = canonical_url or f"https://edorex.test/jobs/{job_id}"
    return f"""
    <html>
      <head><link rel="canonical" href="{canonical}"></head>
      <body><main>
        <section><h1>{title}</h1></section>
        <section class="bg-gray-50">
          <div class="prose prose-lg max-w-none">
            <h2>Das erwartet dich</h2>
            <p>Du entwickelst nachhaltige Softwarelösungen.</p>
            <h2>Deine Aufgaben</h2>
            <ul>
              <li>Berate unsere Kundinnen und Kunden.</li>
              <li>Arbeite eng mit dem Team zusammen.</li>
            </ul>
          </div>
        </section>
        <a href="{apply_url}">Jetzt bewerben</a>
      </main>
      <script type="application/ld+json">{json.dumps(organization)}</script>
      <script type="application/ld+json">{json.dumps(job)}</script>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "lehrstelle-informatikerin-efz",
            title="Lehrstelle Informatiker:in EFZ",
            employment_type="Lehrstelle",
            posted_label="20.07.2026",
        ),
        listing_card(
            "senior-postgresql-consultant-mwd",
            title="Senior PostgreSQL Consultant (m/w/d)",
        ),
    ]


def test_edorex_collects_full_catalog_and_enriches_every_vacancy() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/jobs":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        job_id = request.url.path.removeprefix("/jobs/")
        is_apprenticeship = job_id == "lehrstelle-informatikerin-efz"
        return httpx.Response(
            200,
            text=detail_html(
                job_id,
                title=(
                    "Lehrstelle Informatiker:in EFZ"
                    if is_apprenticeship
                    else "Senior PostgreSQL Consultant (m/w/d)"
                ),
                employment_type="INTERN" if is_apprenticeship else "FULL_TIME",
                date_posted="2026-07-20" if is_apprenticeship else "2026-03-01",
                apply_url=APPRENTICE_APPLY_URL if is_apprenticeship else SENIOR_APPLY_URL,
            ),
            request=request,
        )

    result = EdorexJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/jobs",
        "/jobs/lehrstelle-informatikerin-efz",
        "/jobs/senior-postgresql-consultant-mwd",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Edorex Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "edorex"
    assert job.title == "Lehrstelle Informatiker:in EFZ"
    assert job.company == "Edorex AG"
    assert job.location == "Ostermundigen, Switzerland"
    assert job.url == "https://edorex.test/jobs/lehrstelle-informatikerin-efz"
    assert job.apply_url == APPRENTICE_APPLY_URL
    assert job.posted_at == "2026-07-20"
    assert job.employment_type == "Lehrstelle"
    assert job.description == (
        "Das erwartet dich\n\n"
        "Du entwickelst nachhaltige Softwarelösungen.\n\n"
        "Deine Aufgaben\n"
        "- Berate unsere Kundinnen und Kunden.\n"
        "- Arbeite eng mit dem Team zusammen."
    )
    assert job.raw["detail"]["id"] == "lehrstelle-informatikerin-efz"
    assert result.jobs[1].apply_url == SENIOR_APPLY_URL
    assert result.jobs[1].employment_type == "Vollzeit"


def test_edorex_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs":
            return httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "senior-postgresql-consultant-mwd",
                            title="Senior PostgreSQL Consultant (m/w/d)",
                        )
                    ]
                ),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        EdorexJobsParser(base_url=BASE_URL, transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior PostgreSQL Consultant (m/w/d)"
    assert job.location == "Ostermundigen, Switzerland"
    assert job.apply_url == job.url
    assert job.description == ("Kurze Zusammenfassung für Senior PostgreSQL Consultant (m/w/d).")
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_edorex_rejects_duplicate_non_swiss_or_unsafe_catalog_records() -> None:
    card = listing_card(
        "senior-postgresql-consultant-mwd",
        title="Senior PostgreSQL Consultant (m/w/d)",
    )

    def parser_for(cards: list[str]) -> EdorexJobsParser:
        return EdorexJobsParser(
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
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parser_for(
            [
                listing_card(
                    "senior-postgresql-consultant-mwd",
                    title="Senior PostgreSQL Consultant (m/w/d)",
                    location="Berlin",
                )
            ]
        ).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parser_for(
            [
                listing_card(
                    "senior-postgresql-consultant-mwd",
                    title="Senior PostgreSQL Consultant (m/w/d)",
                    href=("https://evil.test/jobs/senior-postgresql-consultant-mwd"),
                )
            ]
        ).search(LinkedInSearchRequest())


def test_edorex_rejects_empty_catalog_and_mismatched_detail() -> None:
    empty = EdorexJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html/>", request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        empty.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "senior-postgresql-consultant-mwd",
                title="Senior PostgreSQL Consultant (m/w/d)",
                company_name="Another AG",
            ),
            page_url="https://edorex.test/jobs/senior-postgresql-consultant-mwd",
            expected_url="https://edorex.test/jobs/senior-postgresql-consultant-mwd",
            expected_job_id="senior-postgresql-consultant-mwd",
            expected_title="Senior PostgreSQL Consultant (m/w/d)",
            expected_posted_at="2026-03-01",
            expected_employment_type="Vollzeit",
        )


def test_edorex_wraps_listing_request_failures() -> None:
    parser = EdorexJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_edorex_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["edorex"]
    assert isinstance(parser, EdorexJobsParser)
    assert parser.base_url == settings.edorex_jobs_base_url
    assert parser.detail_workers == settings.edorex_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Edorex", "filters": {}},
            "sources": ["edorex", "edorex"],
        }
    )
    assert request.sources == ["edorex"]


def test_edorex_jobs_render_as_direct_company_imports() -> None:
    job = EdorexJobsParser().normalize_job(
        {
            "id": "senior-postgresql-consultant-mwd",
            "title": "Senior PostgreSQL Consultant (m/w/d)",
            "posted_at": "2026-03-01",
            "employment_type": "Vollzeit",
            "location": "Ostermundigen",
            "summary": "PostgreSQL Beratung.",
            "url": "https://edorex.ch/jobs/senior-postgresql-consultant-mwd",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="edorex-senior-postgresql-consultant-mwd",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Edorex import"
    assert stored["id"] == "edorex-senior-postgresql-consultant-mwd"
