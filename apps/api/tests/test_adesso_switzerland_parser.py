from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.adesso_switzerland import (
    AdessoSwitzerlandJobsParser,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.adesso.ch/de_ch/jobs-karriere/unsere-stellenangebote/"
FEED_URL = f"{BASE_URL}rss_generator-rss0.php?unit=adesso_ch&lang=de"


def listing_url(job_id: str) -> str:
    return f"{BASE_URL}stellenangebot.html?yid={job_id}"


def public_url(job_id: str, slug: str) -> str:
    return f"{BASE_URL}{slug}-de-j{job_id}.html"


def apply_url(job_id: str, slug: str) -> str:
    return f"{BASE_URL}{slug}-de-f{job_id}.html"


def record(
    job_id: str,
    *,
    title: str,
    slug: str,
    locations: list[str],
    departments: list[str] | None = None,
    career_levels: list[str] | None = None,
    posted_at: str = "2026-08-12",
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "slug": slug,
        "locations": locations,
        "departments": departments or ["Consulting", "Software Development"],
        "career_levels": career_levels or ["Professionals", "Senior"],
        "posted_at": posted_at,
        "teaser": "Wir gestalten anspruchsvolle IT-Lösungen gemeinsam.",
    }


def catalog_xml(records: list[dict[str, object]]) -> bytes:
    documents: list[str] = []
    for item in records:
        fields: list[tuple[str, str]] = []
        fields.extend(("location_multi_keyword", str(value)) for value in item["locations"])
        fields.extend(("department_multi_keyword", str(value)) for value in item["departments"])
        fields.extend(("career_level_multi_keyword", str(value)) for value in item["career_levels"])
        fields.extend(
            [
                ("title", str(item["title"])),
                ("link", listing_url(str(item["id"]))),
                ("content", str(item["teaser"])),
                ("last_update_date", f"{item['posted_at']}T00:00:00+02:00"),
                ("content_type_multi_keyword", "jobs"),
                ("mime_type_multi_keyword", "text/html"),
                ("language_multi_keyword", "de"),
            ]
        )
        field_xml = "".join(
            f'<field name="{name}"><![CDATA[{html.escape(value)}]]></field>'
            for name, value in fields
        )
        documents.append(f'<document uid="{item["id"]}">{field_xml}</document>')
    return f'<?xml version="1.0" encoding="utf-8"?><documents>{"".join(documents)}</documents>'.encode()


def detail_html(
    item: dict[str, object],
    *,
    title: str | None = None,
    application_url: str | None = None,
    company: str = "adesso Schweiz AG Jobportal",
) -> str:
    job_id = str(item["id"])
    slug = str(item["slug"])
    locations = [
        {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
                "postalCode": "8000",
                "addressCountry": "CH",
            },
        }
        for location in item["locations"]
    ]
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title or item["title"],
        "description": (
            "<p>Gestalte mit uns exzellente IT-Lösungen.</p>"
            "<h2>Deine Aufgaben</h2><ul><li>Berate unsere Kunden</li></ul>"
        ),
        "datePosted": item["posted_at"],
        "validThrough": "2027-02-01",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": locations if len(locations) > 1 else locations[0],
    }
    return f"""
    <html><head>
      <link rel="canonical" href="{public_url(job_id, slug)}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <div id="btn_online_application">
        <a href="{application_url or apply_url(job_id, slug)}?sid=session-value">
          Jetzt bewerben!
        </a>
      </div>
    </body></html>
    """


def official_records() -> list[dict[str, object]]:
    return [
        record(
            "2956",
            title="Senior Consultant Business Automation & Project Management (all genders)",
            slug="Senior-Consultant-Business-Automation-Project-Management-a",
            locations=["Zürich"],
            career_levels=["Professionals", "Senior", "Young Professionals"],
        ),
        record(
            "2954",
            title="Teamlead Microsoft Cloud & AI Platforms (all genders)",
            slug="Teamlead-Microsoft-Cloud-AI-Platforms-all-genders",
            locations=["Basel", "Bern", "St. Gallen", "Zürich"],
            departments=["Consulting", "Microsoft"],
            career_levels=["Senior"],
            posted_at="2026-07-28",
        ),
    ]


def test_adesso_scans_complete_catalog_and_enriches_details() -> None:
    records = official_records()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_xml(records))
        job_id = parse_qs(request.url.query.decode())["yid"][0]
        item = next(value for value in records if value["id"] == job_id)
        return httpx.Response(200, text=detail_html(item))

    result = AdessoSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 3
    assert str(requests[0].url) == FEED_URL
    assert result.message == (
        "Scanned 2 Adesso Switzerland vacancies from the complete official catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "adesso_switzerland"
    assert first.title and first.title.startswith("Senior Consultant Business")
    assert first.company == "adesso Schweiz AG"
    assert first.location == "Zürich, Switzerland"
    assert first.url == public_url("2956", str(records[0]["slug"]))
    assert first.apply_url == apply_url("2956", str(records[0]["slug"]))
    assert first.posted_at == "2026-08-12"
    assert first.employment_type == "Full-time"
    assert first.seniority == "Professionals, Senior, Young Professionals"
    assert first.description and "Gestalte mit uns" in first.description
    assert first.description and "- Berate unsere Kunden" in first.description
    assert first.raw["departments"] == ["Consulting", "Software Development"]
    assert first.raw["detail"]["schema"]["@type"] == "JobPosting"
    assert result.jobs[1].location == (
        "Basel, Switzerland; Bern, Switzerland; St. Gallen, Switzerland; Zürich, Switzerland"
    )


def test_adesso_preserves_catalog_record_when_detail_fails() -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_xml([item]))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        AdessoSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.url == listing_url("2956")
    assert job.apply_url == listing_url("2956")
    assert job.description == "Wir gestalten anspruchsvolle IT-Lösungen gemeinsam."
    assert job.employment_type is None
    assert "503" in str(job.raw["detail_error"])


def test_adesso_rejects_mismatched_detail_but_keeps_catalog_record() -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_xml([item]))
        return httpx.Response(200, text=detail_html(item, title="Different vacancy"))

    job = (
        AdessoSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.url == listing_url("2956")
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_adesso_rejects_untrusted_apply_url() -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_xml([item]))
        return httpx.Response(
            200,
            text=detail_html(
                item,
                application_url="https://example.com/apply/2956",
            ),
        )

    job = (
        AdessoSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == listing_url("2956")
    assert "incomplete or mismatched" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "payload,error",
    [
        (b"<documents><document>", "XML is malformed"),
        (b"<!DOCTYPE documents><documents />", "XML is unsafe"),
        (
            catalog_xml(
                [
                    record(
                        "2956",
                        title="Unexpected location",
                        slug="Unexpected-location",
                        locations=["Berlin"],
                    )
                ]
            ),
            "unexpected vacancy",
        ),
    ],
)
def test_adesso_rejects_malformed_or_unexpected_catalog(
    payload: bytes,
    error: str,
) -> None:
    parser = AdessoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match=error):
        parser.search(LinkedInSearchRequest())


def test_adesso_rejects_duplicate_ids() -> None:
    item = official_records()[0]
    parser = AdessoSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=catalog_xml([item, item]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_adesso_accepts_an_empty_official_catalog() -> None:
    parser = AdessoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=catalog_xml([])))
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Adesso Switzerland vacancies from the complete official catalog"
    )


def test_adesso_wraps_catalog_request_failures() -> None:
    parser = AdessoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_adesso_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["adesso_switzerland"]
    assert isinstance(parser, AdessoSwitzerlandJobsParser)
    assert parser.base_url == settings.adesso_switzerland_jobs_base_url
    assert parser.feed_url == settings.adesso_switzerland_jobs_feed_url
    assert parser.detail_workers == settings.adesso_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Adesso Switzerland", "filters": {}},
            "sources": ["adesso_switzerland", "adesso_switzerland"],
        }
    )
    assert request.sources == ["adesso_switzerland"]


def test_adesso_jobs_render_as_direct_company_imports() -> None:
    item = official_records()[0]
    parsed = {
        "id": item["id"],
        "title": item["title"],
        "company": "adesso Schweiz AG",
        "locations": item["locations"],
        "url": listing_url("2956"),
        "posted_at": item["posted_at"],
        "career_levels": item["career_levels"],
    }
    job = AdessoSwitzerlandJobsParser().normalize_job(parsed)
    stored = parsed_job_to_stored_job(
        job,
        job_id="adesso_switzerland-2956",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "www.adesso.ch"
    assert stored["logo"] == "company"
    assert stored["department"] == "Adesso Switzerland import"
    assert stored["id"] == "adesso_switzerland-2956"
