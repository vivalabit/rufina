from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.electrosuisse import ElectrosuisseJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

HELPDESK_JOB_ID = "80275"
FRENCH_JOB_ID = "79458"
HELPDESK_TOKEN = (
    "txxoay0p0zcmnoxacizt4e8i47uypwxeps0ycp0kz07o80oibt1uo43m65vwiuq6"
)
FRENCH_TOKEN = (
    "6fjy85tlp6287hb8fnwjuvdepx2vgkb6mqsr4d6lywffh7grzv4g7ya9l6mwofli"
)


def detail_url(slug: str, token: str) -> str:
    return f"https://jobs.electrosuisse.ch/publication/{slug}/{token}"


def listing_record(
    job_id: str,
    *,
    title: str,
    slug: str,
    token: str,
    city: str = "Fehraltorf",
    postal_code: str = "8320",
    language: str = "Deutsch",
    langcode: str = "DE",
    employment_type: str = "Temporäre Anstellung",
    workload: str = "80 - 100%",
) -> dict[str, object]:
    url = detail_url(slug, token)
    return {
        "id": int(job_id),
        "reference": job_id,
        "title": title,
        "country": "Schweiz",
        "countrycode": "CH",
        "city": city,
        "zip": postal_code,
        "published": "10.08.2026",
        "timestamp": "1786320000",
        "type": employment_type,
        "position": "Fachmitarbeiter/-in mit Berufserfahrung",
        "workload": workload,
        "workload_min": "80",
        "workload_max": "100",
        "company": "",
        "department": "Finanzen und Administration",
        "detail": url,
        "action": url,
        "actionTarget": "_blank",
        "button": "Zum Inserat",
        "image": "",
        "text": "",
        "startdate": "",
        "timestamp2": "0",
        "language": language,
        "langcode": langcode,
    }


def catalog_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "jobs": records,
        "error": {"message": ""},
        "options": {"page": 25},
        "translations": {},
    }


def detail_html(
    *,
    title: str,
    token: str,
    locality: str = "Fehraltorf",
    postal_code: str = "8320",
    country: str = "CH",
    company: str = "Electrosuisse",
    language: str = "DE",
    employment_type: object = None,
) -> str:
    apply_url = (
        "https://jobs.electrosuisse.ch/cvdropper/"
        f"a5d8bc2849464896a66452ba778570fb/{language}?src={token}"
    )
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<p>Electrosuisse löst anspruchsvolle technische Herausforderungen.</p>"
            "<h3>Deine Aufgaben</h3>"
            "<ul><li>Supportanfragen beantworten</li></ul>"
            f'<a href="{apply_url}">Jetzt bewerben</a>'
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": "1366",
        },
        "datePosted": "2026-08-10",
        "employmentType": employment_type or ["PART_TIME", "TEMPORARY"],
        "hiringOrganization": {
            "@type": "Organization",
            "name": company,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Luppmenstrasse 1",
                "addressLocality": locality,
                "postalCode": postal_code,
                "addressRegion": "ZH",
                "addressCountry": country,
            },
        },
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def official_catalog() -> list[dict[str, object]]:
    return [
        listing_record(
            HELPDESK_JOB_ID,
            title="IT Helpdesk Support 1st and 2nd Level 80 - 100% (a)",
            slug="it-helpdesk-support-st-and-nd-level",
            token=HELPDESK_TOKEN,
        ),
        listing_record(
            FRENCH_JOB_ID,
            title="Conseiller en sécurité électrique Région Arc lémanique",
            slug="conseiller-en-securite-electrique-region-arc-lemanique",
            token=FRENCH_TOKEN,
            city="Bulle",
            postal_code="1630",
            language="Französisch",
            langcode="FR",
            employment_type="Festanstellung",
        ),
    ]


def test_electrosuisse_collects_complete_catalog_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "odm.ostendis.com":
            assert request.url.params["domain"] == "www.electrosuisse.ch"
            return httpx.Response(200, json=catalog_payload(official_catalog()))
        if request.url.path.endswith(HELPDESK_TOKEN):
            return httpx.Response(
                200,
                text=detail_html(
                    title="IT Helpdesk Support 1st and 2nd Level 80 - 100% (a)",
                    token=HELPDESK_TOKEN,
                ),
            )
        if request.url.path.endswith(FRENCH_TOKEN):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Conseiller en sécurité électrique Région Arc lémanique",
                    token=FRENCH_TOKEN,
                    language="FR",
                    employment_type="FULL_TIME",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = ElectrosuisseJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Electrosuisse vacancies from the official catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "electrosuisse"
    assert first.title == "IT Helpdesk Support 1st and 2nd Level 80 - 100% (a)"
    assert first.company == "Electrosuisse"
    assert first.location == "8320 Fehraltorf, Switzerland"
    assert first.url == detail_url(
        "it-helpdesk-support-st-and-nd-level",
        HELPDESK_TOKEN,
    )
    assert first.apply_url == (
        "https://jobs.electrosuisse.ch/cvdropper/"
        f"a5d8bc2849464896a66452ba778570fb/DE?src={HELPDESK_TOKEN}"
    )
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == (
        "Part-time, Temporary · Temporäre Anstellung · 80 - 100%"
    )
    assert first.seniority == "Fachmitarbeiter/-in mit Berufserfahrung"
    assert first.description and "technische Herausforderungen" in first.description
    assert first.description and "- Supportanfragen beantworten" in first.description
    assert first.raw["id"] == HELPDESK_JOB_ID
    assert first.raw["detail"]["schema"]["@type"] == "JobPosting"
    assert result.jobs[1].location == "1630 Bulle, Switzerland"
    assert result.jobs[1].apply_url and "/FR?src=" in result.jobs[1].apply_url


def test_electrosuisse_preserves_safe_listing_when_detail_fails() -> None:
    record = official_catalog()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload([record]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        ElectrosuisseJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "IT Helpdesk Support 1st and 2nd Level 80 - 100% (a)"
    assert job.company == "Electrosuisse"
    assert job.location == "8320 Fehraltorf, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at == "2026-08-10"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_electrosuisse_rejects_malformed_or_non_swiss_catalog() -> None:
    malformed = ElectrosuisseJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": "not-a-list"})
        )
    )
    foreign_record = official_catalog()[0]
    foreign_record["countrycode"] = "DE"
    foreign = ElectrosuisseJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=catalog_payload([foreign_record]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="payload is malformed"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        foreign.search(LinkedInSearchRequest())


def test_electrosuisse_rejects_mismatched_detail_but_keeps_listing() -> None:
    record = official_catalog()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload([record]))
        return httpx.Response(
            200,
            text=detail_html(
                title="Different vacancy",
                token=HELPDESK_TOKEN,
                locality="Berlin",
                country="DE",
            ),
        )

    job = (
        ElectrosuisseJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "8320 Fehraltorf, Switzerland"
    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_electrosuisse_accepts_an_empty_official_catalog() -> None:
    parser = ElectrosuisseJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=catalog_payload([]))
        )
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Electrosuisse vacancies from the official catalog"
    )


def test_electrosuisse_wraps_listing_request_failures() -> None:
    parser = ElectrosuisseJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(503, text="unavailable")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_electrosuisse_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["electrosuisse"]
    assert isinstance(parser, ElectrosuisseJobsParser)
    assert parser.base_url == settings.electrosuisse_jobs_base_url
    assert parser.api_url == settings.electrosuisse_jobs_api_url
    assert parser.detail_workers == settings.electrosuisse_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Electrosuisse", "filters": {}},
            "sources": ["electrosuisse", "electrosuisse"],
        }
    )
    assert request.sources == ["electrosuisse"]


def test_electrosuisse_jobs_render_as_direct_company_imports() -> None:
    record = official_catalog()[0]
    record["id"] = HELPDESK_JOB_ID
    record["url"] = record["detail"]
    job = ElectrosuisseJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"electrosuisse-{HELPDESK_JOB_ID}",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "jobs.electrosuisse.ch"
    assert stored["logo"] == "company"
    assert stored["department"] == "Electrosuisse import"
    assert stored["id"] == f"electrosuisse-{HELPDESK_JOB_ID}"
