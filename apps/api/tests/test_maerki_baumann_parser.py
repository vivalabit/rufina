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
from app.services.parsers.companies.maerki_baumann import MaerkiBaumannJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

CUSTOMER_JOB_ID = "78216"
APPRENTICESHIP_JOB_ID = "79000"
CUSTOMER_TOKEN = "laf7dlp8054scp0fmzm76cqyxe4tzdzlremc3rw73e7qrzeq7t7gg2inv6pw3gis"
APPRENTICESHIP_TOKEN = "ctn72e00wrfs0ex5i3ot02no664zg40jyer5isvwjaadop32jcgh3pyx0qm4o707"


def detail_url(slug: str, token: str) -> str:
    return f"https://jobs.maerki-baumann.ch/publication/{slug}/{token}"


def listing_record(
    job_id: str,
    *,
    title: str,
    slug: str,
    token: str,
    employment_type: str = "Festanstellung",
    position: str = "Fachmitarbeiter/-in mit Berufserfahrung",
) -> dict[str, object]:
    url = detail_url(slug, token)
    return {
        "id": int(job_id),
        "reference": job_id,
        "title": title,
        "country": "Schweiz",
        "countrycode": "CH",
        "city": "Zürich",
        "zip": "8002",
        "published": "27.07.2026",
        "timestamp": "1785110400",
        "type": employment_type,
        "position": position,
        "workload": "100%",
        "workload_min": "100",
        "workload_max": "100",
        "company": "",
        "department": "",
        "detail": url,
        "action": url,
        "actionTarget": "_blank",
        "button": "Zum Inserat",
        "image": "",
        "text": "",
        "startdate": "",
        "timestamp2": "1782864000",
        "language": "Deutsch",
        "langcode": "DE",
    }


def catalog_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "jobs": records,
        "error": {"message": ""},
        "options": {"page": 5},
        "translations": {},
    }


def detail_html(
    *,
    title: str,
    token: str,
    locality: str = "Zürich",
    country: str = "CH",
    company: str = "Maerki Baumann & Co. AG",
    employment_type: str = "FULL_TIME",
) -> str:
    apply_url = (
        f"https://jobs.maerki-baumann.ch/cvdropper/d5041040fe8948a197f62104eca6e804/DE?src={token}"
    )
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<p>Die Privatbank sucht eine engagierte Persönlichkeit.</p>"
            "<h3>Aufgabenbereich</h3>"
            "<ul><li>Kundendokumentation prüfen</li></ul>"
            f'<a href="{apply_url}">Jetzt bewerben</a>'
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": "1813",
        },
        "datePosted": "2026-07-27",
        "employmentType": [employment_type, employment_type],
        "hiringOrganization": {
            "@type": "Organization",
            "name": company,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Dreikönigstrasse 6",
                "addressLocality": locality,
                "postalCode": "8002",
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
            CUSTOMER_JOB_ID,
            title="Mitarbeiter/in Kundendokumentation (100 %)",
            slug="mitarbeiter-in-kundendokumentation",
            token=CUSTOMER_TOKEN,
        ),
        listing_record(
            APPRENTICESHIP_JOB_ID,
            title="Lehrstelle als Kauffrau/Kaufmann EFZ Bank (100 %)",
            slug="lehrstelle-als-kauffrau-kaufmann-efz-bank",
            token=APPRENTICESHIP_TOKEN,
            employment_type="Lehrstelle",
            position="Lernende/-r",
        ),
    ]


def test_maerki_baumann_collects_complete_catalog_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "odm.ostendis.com":
            assert request.url.params["domain"] == "www.maerki-baumann.ch"
            return httpx.Response(200, json=catalog_payload(official_catalog()))
        if request.url.path.endswith(CUSTOMER_TOKEN):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Mitarbeiter/in Kundendokumentation (100 %)",
                    token=CUSTOMER_TOKEN,
                ),
            )
        if request.url.path.endswith(APPRENTICESHIP_TOKEN):
            return httpx.Response(
                200,
                text=detail_html(
                    title="Lehrstelle als Kauffrau/Kaufmann EFZ Bank (100 %)",
                    token=APPRENTICESHIP_TOKEN,
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = MaerkiBaumannJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Maerki Baumann vacancies from the official catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "maerki_baumann"
    assert first.title == "Mitarbeiter/in Kundendokumentation (100 %)"
    assert first.company == "Maerki Baumann & Co. AG"
    assert first.location == "8002 Zürich, Switzerland"
    assert first.url == detail_url(
        "mitarbeiter-in-kundendokumentation",
        CUSTOMER_TOKEN,
    )
    assert first.apply_url == (
        "https://jobs.maerki-baumann.ch/cvdropper/"
        f"d5041040fe8948a197f62104eca6e804/DE?src={CUSTOMER_TOKEN}"
    )
    assert first.posted_at == "2026-07-27"
    assert first.employment_type == "Full-time · Festanstellung · 100%"
    assert first.seniority == "Fachmitarbeiter/-in mit Berufserfahrung"
    assert first.description and "Privatbank sucht" in first.description
    assert first.description and "- Kundendokumentation prüfen" in first.description
    assert first.raw["id"] == CUSTOMER_JOB_ID
    assert first.raw["detail"]["schema"]["@type"] == "JobPosting"
    assert result.jobs[1].employment_type == "Full-time · Lehrstelle · 100%"
    assert result.jobs[1].seniority == "Lernende/-r"


def test_maerki_baumann_preserves_safe_listing_when_detail_fails() -> None:
    record = official_catalog()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload([record]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        MaerkiBaumannJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Mitarbeiter/in Kundendokumentation (100 %)"
    assert job.company == "Maerki Baumann & Co. AG"
    assert job.location == "8002 Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at == "2026-07-27"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_maerki_baumann_rejects_malformed_or_non_swiss_catalog() -> None:
    malformed = MaerkiBaumannJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"jobs": "not-a-list"}))
    )
    foreign_record = official_catalog()[0]
    foreign_record["countrycode"] = "DE"
    foreign = MaerkiBaumannJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=catalog_payload([foreign_record]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="payload is malformed"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        foreign.search(LinkedInSearchRequest())


def test_maerki_baumann_rejects_mismatched_detail_but_keeps_listing() -> None:
    record = official_catalog()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload([record]))
        return httpx.Response(
            200,
            text=detail_html(
                title="Different vacancy",
                token=CUSTOMER_TOKEN,
                locality="Berlin",
                country="DE",
            ),
        )

    job = (
        MaerkiBaumannJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "8002 Zürich, Switzerland"
    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_maerki_baumann_accepts_an_empty_official_catalog() -> None:
    parser = MaerkiBaumannJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=catalog_payload([])))
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == ("Scanned 0 Maerki Baumann vacancies from the official catalog")


def test_maerki_baumann_wraps_listing_request_failures() -> None:
    parser = MaerkiBaumannJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_maerki_baumann_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["maerki_baumann"]
    assert isinstance(parser, MaerkiBaumannJobsParser)
    assert parser.base_url == settings.maerki_baumann_jobs_base_url
    assert parser.api_url == settings.maerki_baumann_jobs_api_url
    assert parser.detail_workers == settings.maerki_baumann_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Maerki Baumann", "filters": {}},
            "sources": ["maerki_baumann", "maerki_baumann"],
        }
    )
    assert request.sources == ["maerki_baumann"]


def test_maerki_baumann_jobs_render_as_direct_company_imports() -> None:
    record = official_catalog()[0]
    record["id"] = CUSTOMER_JOB_ID
    record["url"] = record["detail"]
    job = MaerkiBaumannJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"maerki_baumann-{CUSTOMER_JOB_ID}",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "jobs.maerki-baumann.ch"
    assert stored["logo"] == "company"
    assert stored["department"] == "Maerki Baumann import"
    assert stored["id"] == f"maerki_baumann-{CUSTOMER_JOB_ID}"
