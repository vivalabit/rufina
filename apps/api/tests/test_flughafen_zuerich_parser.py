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
from app.services.parsers.companies.flughafen_zuerich import (
    FlughafenZuerichJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    *,
    job_id: str,
    view_key: str,
    slug: str,
    title: str,
    workload: str,
    department: str,
    seniority: str,
) -> dict[str, object]:
    return {
        "id": job_id,
        "viewKey": view_key,
        "title": title,
        "relevantFilters": [
            {
                "filterId": "30",
                "filterName": "Beschäftigungsgrad",
                "filterOptions": [{"optionId": "1574784", "optionValue": workload}],
            },
            {
                "filterId": "10",
                "filterName": "Tätigkeitsgebiet",
                "filterOptions": [{"optionId": "1574760", "optionValue": department}],
            },
            {
                "filterId": "20",
                "filterName": "Position",
                "filterOptions": [{"optionId": "1574777", "optionValue": seniority}],
            },
        ],
        "shortDescription": f"Short description for {title} &amp; team.",
        "jobLink": (
            f"https://jobs-karriere.flughafen-zuerich.test/offene-stellen/{slug}/{view_key}"
        ),
    }


def listing_payload() -> list[dict[str, object]]:
    return [
        listing_record(
            job_id="10105520",
            view_key="259f2885-f0d5-438d-ad12-4bb265123bdf",
            slug="betriebselektriker-in-instandhaltung",
            title="Betriebselektriker:in Instandhaltung 80 - 100%",
            workload="80%-100%",
            department="Handwerk & Technik",
            seniority="Mitarbeiter:in",
        ),
        listing_record(
            job_id="10139144",
            view_key="9aa055b7-f31a-45e9-95e8-f3a60cc674f1",
            slug="network-security-operation-system-engineer",
            title="Network & Security Operation System Engineer 80 - 100%",
            workload="80%-100%",
            department="Informatik",
            seniority="Mitarbeiter:in",
        ),
    ]


def detail_html(*, view_key: str, title: str) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<h3>Keep critical airport systems reliable.</h3><br><br>"
            "<div>Deine Jobdestination</div><br>"
            "<ul><li>Own production systems.</li>"
            "<li>Support airport operations.</li></ul>"
        ),
        "datePosted": "2026-07-08",
        "validThrough": "2028-07-06",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Flughafen Zürich AG",
        },
        "employmentType": "PART_TIME",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "Schweiz",
                "addressLocality": "Flughafen Zürich",
                "addressRegion": "Region Zürich",
            },
        },
    }
    return f"""
    <html><head>
      <link rel="canonical" href="https://jobs-karriere.flughafen-zuerich.test/offene-stellen/airport-role/{view_key}">
    </head><body>
      <a class="apply button blue" href="/apply/ats/{view_key}">Jetzt bewerben</a>
    </body></html><script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_flughafen_zuerich_scans_and_enriches_full_catalog() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/jobs/jobs":
            assert request.headers["sc_apikey"] == "public-test-key"
            assert request.headers["referer"] == (
                "https://www.flughafen-zuerich.test/stellenangebote"
            )
            return httpx.Response(200, json=listing_payload())
        view_key = request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        title = (
            "Betriebselektriker:in Instandhaltung 80 - 100%"
            if view_key.startswith("259f")
            else "Network & Security Operation System Engineer 80 - 100%"
        )
        return httpx.Response(
            200,
            text=detail_html(view_key=view_key, title=title),
        )

    parser = FlughafenZuerichJobsParser(
        base_url="https://www.flughafen-zuerich.test/stellenangebote",
        api_url="https://www.flughafen-zuerich.test/api/jobs/jobs",
        api_key="public-test-key",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 Flughafen Zürich vacancies from the official API")
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "flughafen_zuerich"
    assert first.title == "Betriebselektriker:in Instandhaltung 80 - 100%"
    assert first.company == "Flughafen Zürich AG"
    assert first.location == "Flughafen Zürich"
    assert first.url == (
        "https://jobs-karriere.flughafen-zuerich.test/"
        "offene-stellen/airport-role/259f2885-f0d5-438d-ad12-4bb265123bdf"
    )
    assert first.apply_url == (
        "https://jobs-karriere.flughafen-zuerich.test/"
        "apply/ats/259f2885-f0d5-438d-ad12-4bb265123bdf"
    )
    assert first.posted_at == "2026-07-08"
    assert first.employment_type == "80%-100%"
    assert first.seniority == "Mitarbeiter:in"
    assert first.description == (
        "Keep critical airport systems reliable.\n\n"
        "Deine Jobdestination\n\n"
        "- Own production systems.\n"
        "- Support airport operations."
    )
    assert first.raw["id"] == "10105520"
    assert first.raw["viewKey"] == "259f2885-f0d5-438d-ad12-4bb265123bdf"
    assert first.raw["detail"]["valid_through"] == "2028-07-06"


def test_flughafen_zuerich_preserves_listing_when_detail_fails() -> None:
    payload = listing_payload()[:1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/jobs/jobs":
            return httpx.Response(200, json=payload)
        return httpx.Response(503, text="temporarily unavailable")

    parser = FlughafenZuerichJobsParser(
        api_url="https://www.flughafen-zuerich.test/api/jobs/jobs",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Betriebselektriker:in Instandhaltung 80 - 100%"
    assert job.location == "Flughafen Zürich"
    assert job.posted_at is None
    assert job.description == (
        "Short description for Betriebselektriker:in Instandhaltung 80 - 100% & team."
    )
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_flughafen_zuerich_rejects_invalid_api_contract() -> None:
    parser = FlughafenZuerichJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"jobs": listing_payload()})
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="must return a list"):
        parser.search(LinkedInSearchRequest())


def test_flughafen_zuerich_rejects_duplicate_vacancy_ids() -> None:
    payload = listing_payload()
    payload[1]["id"] = payload[0]["id"]
    parser = FlughafenZuerichJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_flughafen_zuerich_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["flughafen_zuerich"]
    assert isinstance(parser, FlughafenZuerichJobsParser)
    assert parser.base_url == settings.flughafen_zuerich_jobs_base_url
    assert parser.api_url == settings.flughafen_zuerich_jobs_api_url
    assert parser.api_key == settings.flughafen_zuerich_jobs_api_key
    assert parser.detail_workers == settings.flughafen_zuerich_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Flughafen Zürich", "filters": {}},
            "sources": ["flughafen_zuerich", "flughafen_zuerich"],
        }
    )
    assert request.sources == ["flughafen_zuerich"]


def test_flughafen_zuerich_jobs_render_as_direct_company_imports() -> None:
    parser = FlughafenZuerichJobsParser()
    job = parser.normalize_job(listing_payload()[0])
    stored = parsed_job_to_stored_job(
        job,
        job_id="flughafen_zuerich-10105520",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Flughafen Zürich import"
    assert stored["id"] == "flughafen_zuerich-10105520"
