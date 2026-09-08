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
from app.services.parsers.companies.huerlimann_informatik import (
    HUERLIMANN_API_URL,
    HuerlimannInformatikJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://hi-ag.test/unternehmen/karriere"
API_URL = (
    "https://odm.ostendis.com/ojp/data/v55/jobs/"
    "7e4b4ce19bfa48e5838035fcadc5be54/DE?domain=www.hi-ag.ch"
)
JOB_ID = "75877"
TOKEN = "hh42bwq2i7ompweoc5gbh0kcccpi85krel4d3f3wtzayg0t2mji6rizbioz575ep"
DETAIL_URL = f"https://link.ostendis.com/publication/abteilungsleiter-in-technik-support/{TOKEN}"
APPLY_URL = f"https://link.ostendis.com/cvdropper/445ea227dcd5479ca9345c40d8f6ed78/DE?src={TOKEN}"
SPONTANEOUS_URL = (
    "https://link.ostendis.com/cvdropper/cece2c7efba84a18a5ed04d1e5bb36a5/"
    "DE?src=xeewza360dx8i7yfpw3cyc2fapmheaccicop5m2xxiwwixnnvzrpxi2ke4myw1jq"
)


def careers_html(*, site_name: str = "Hürlimann Informatik", token: str | None = None) -> str:
    portal_token = token or "7e4b4ce19bfa48e5838035fcadc5be54"
    return f"""
    <html lang="de">
      <head>
        <meta name="Generator" content="Drupal 11 (https://www.drupal.org)">
        <meta property="og:site_name" content="{site_name}">
        <link rel="canonical" href="{BASE_URL}">
      </head>
      <body>
        <div id="karriere-1266-panel-2">
          <script id="ostendisLoader"
            src="https://odm.ostendis.com/ojp/assets/loader"
            data-token="{portal_token}"></script>
          <div id="ostendisJobs"></div>
          <script>
            OSTENDISJOBS.embed(
              "{portal_token}", "DE", "#ostendisJobs", {{}}
            );
          </script>
        </div>
        <div id="karriere-1266-panel-3">
          <a href="{SPONTANEOUS_URL}">Spontanbewerbung</a>
          <a href="{SPONTANEOUS_URL}">Bewerben</a>
        </div>
      </body>
    </html>
    """


def listing_record(*, country_code: str = "CH", action: str = APPLY_URL) -> dict[str, object]:
    return {
        "id": int(JOB_ID),
        "reference": JOB_ID,
        "title": "Abteilungsleiter/in Technik & Support 100%",
        "country": "Schweiz",
        "countrycode": country_code,
        "city": "Obfelden",
        "zip": "8912",
        "published": "09.04.2026",
        "type": "Festanstellung",
        "position": "Führungskraft / Geschäftsleitung",
        "workload": "100%",
        "detail": DETAIL_URL,
        "action": action,
        "language": "Deutsch",
        "langcode": "DE",
    }


def catalog_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {"jobs": records, "error": {"message": ""}, "options": {"page": 5}}


def detail_html(
    *,
    title: str = "Abteilungsleiter/in Technik & Support 100%",
    company: str = "Hürlimann Informatik AG",
    country: str = "CH",
    apply_url: str = APPLY_URL,
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<p>Wir entwickeln IT-Gesamtlösungen für öffentliche Verwaltungen.</p>"
            "<h3>Kernaufgaben</h3><ul><li>Du führst Technik und Support.</li></ul>"
            f'<a href="{apply_url}">Jetzt bewerben</a>'
        ),
        "datePosted": "2026-04-09",
        "employmentType": ["FULL_TIME", "FULL_TIME"],
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Obfelden",
                "postalCode": "8912",
                "addressCountry": country,
            },
        },
    }
    return f'<html><body><script type="application/ld+json">{json.dumps(schema)}</script></body></html>'


def handler_for(records: list[dict[str, object]], *, details: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hi-ag.test":
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload(records), request=request)
        return httpx.Response(200, text=details or detail_html(), request=request)

    return handler


def test_huerlimann_collects_complete_catalog_with_details() -> None:
    result = HuerlimannInformatikJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler_for([listing_record()])),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 1 Hürlimann Informatik Switzerland vacancies from the official catalog"
    )
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source == "huerlimann_informatik"
    assert job.title == "Abteilungsleiter/in Technik & Support 100%"
    assert job.company == "Hürlimann Informatik AG"
    assert job.location == "8912 Obfelden, Switzerland"
    assert job.url == DETAIL_URL
    assert job.apply_url == APPLY_URL
    assert job.posted_at == "2026-04-09"
    assert job.employment_type == "Full-time · Festanstellung · 100%"
    assert job.seniority == "Führungskraft / Geschäftsleitung"
    assert job.description and "IT-Gesamtlösungen" in job.description
    assert job.description and "- Du führst Technik und Support" in job.description


def test_huerlimann_preserves_safe_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hi-ag.test":
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload([listing_record()]), request=request)
        return httpx.Response(503, request=request)

    job = (
        HuerlimannInformatikJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.apply_url == APPLY_URL
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_huerlimann_rejects_wrong_career_identity_or_portal() -> None:
    def run(page: str) -> None:
        HuerlimannInformatikJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity or job portal"):
        run(careers_html(site_name="Attacker AG"))
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity or job portal"):
        run(careers_html(token="00000000000000000000000000000000"))


def test_huerlimann_rejects_invalid_catalog_records() -> None:
    def run(record: dict[str, object]) -> None:
        HuerlimannInformatikJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler_for([record])),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        run(listing_record(country_code="DE"))
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        run(listing_record(action="https://attacker.example/apply"))
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        HuerlimannInformatikJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler_for([listing_record(), listing_record()])),
        ).search(LinkedInSearchRequest())


def test_huerlimann_rejects_mismatched_detail_but_keeps_listing() -> None:
    job = (
        HuerlimannInformatikJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(
                handler_for(
                    [listing_record()],
                    details=detail_html(company="Attacker AG", country="DE"),
                )
            ),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.location == "8912 Obfelden, Switzerland"
    assert job.apply_url == APPLY_URL
    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_huerlimann_accepts_empty_catalog_and_wraps_request_failures() -> None:
    result = HuerlimannInformatikJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler_for([])),
    ).search(LinkedInSearchRequest())
    assert result.jobs == []

    parser = HuerlimannInformatikJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_huerlimann_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["huerlimann_informatik"]
    assert isinstance(parser, HuerlimannInformatikJobsParser)
    assert parser.base_url == settings.huerlimann_informatik_jobs_base_url
    assert parser.api_url == HUERLIMANN_API_URL
    assert parser.detail_workers == settings.huerlimann_informatik_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Hürlimann Informatik", "filters": {}},
            "sources": ["huerlimann_informatik", "huerlimann_informatik"],
        }
    )
    assert request.sources == ["huerlimann_informatik"]

    job = normalize_job(
        {
            "id": JOB_ID,
            "title": "Abteilungsleiter/in Technik & Support 100%",
            "url": DETAIL_URL,
            "apply_url": APPLY_URL,
            "city": "Obfelden",
            "zip": "8912",
            "countrycode": "CH",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"huerlimann_informatik-{JOB_ID}",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Hürlimann Informatik AG import"
    assert stored["id"] == f"huerlimann_informatik-{JOB_ID}"


def test_huerlimann_recognizes_no_open_positions_but_not_other_errors() -> None:
    from app.services.parsers.companies.huerlimann_informatik import parse_catalog_payload

    payload = catalog_payload([])
    payload["error"] = {"message": "Aktuell sind keine offenen Stellen vorhanden."}
    assert parse_catalog_payload(payload) == []
    payload["jobs"] = [listing_record()]
    with pytest.raises(DirectCompanyRequestError):
        parse_catalog_payload(payload)
    payload["jobs"] = []
    payload["error"] = {"message": "Service unavailable"}
    with pytest.raises(DirectCompanyRequestError):
        parse_catalog_payload(payload)
