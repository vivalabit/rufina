from __future__ import annotations

import html
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.amag_group import (
    AmagGroupJobsParser,
    AmagGroupParseError,
    normalize_job,
    parse_catalog_atom,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://jobs.amag-group.ch/"
FEED_URL = f"{BASE_URL}rss_generator-rss0.php?unit=amag&lang=de"


def public_url(job_id: str, slug: str) -> str:
    return f"{BASE_URL}{slug}-de-j{job_id}.html"


def apply_url(job_id: str, slug: str) -> str:
    return f"{BASE_URL}{slug}-de-f{job_id}.html"


def record(
    job_id: str,
    *,
    title: str,
    slug: str,
    posted_at: str = "2026-08-13",
    category: str = "Informatik",
) -> dict[str, str]:
    return {
        "id": job_id,
        "title": title,
        "slug": slug,
        "posted_at": posted_at,
        "category": category,
        "summary": "Wir bewegen und begeistern Menschen. Einfach. Nachhaltig. Voraus.",
    }


def catalog_atom(records: list[dict[str, str]]) -> bytes:
    entries = []
    for item in records:
        alias_url = public_url(item["id"], item["slug"]).replace(
            "jobs.amag-group.ch", "jobs.amag.ch"
        )
        entries.append(
            f"""
            <entry>
              <title>{html.escape(item["title"])}</title>
              <category term="{html.escape(item["category"])}" />
              <link href="{alias_url}" />
              <id>{alias_url}</id>
              <summary type="html">{html.escape(item["summary"])}</summary>
              <updated>{item["posted_at"]}T00:00:00+02:00</updated>
            </entry>
            """
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>AMAG Group - Jobs &amp; Karriere</title>
      <link href="https://jobs.amag-group.ch/" />
      <author><name>AMAG Group</name></author>
      <id>https://jobs.amag-group.ch/</id>
      <updated>2026-08-16T13:16:59+02:00</updated>
      {"".join(entries)}
    </feed>""".encode()


def detail_html(
    item: dict[str, str],
    *,
    country: str = "CH",
    city: str = "Cham",
    title: str | None = None,
    application_url: str | None = None,
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title or item["title"],
        "description": (
            "<h2>Wir bewegen Menschen</h2><p>Gestalte die Mobilität von morgen.</p>"
            "<ul><li>Entwickle nachhaltige Lösungen</li></ul>"
        ),
        "datePosted": item["posted_at"],
        "validThrough": "2026-10-14",
        "directApply": True,
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "AMAG Group"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city,
                "postalCode": "6330",
                "addressCountry": country,
            },
        },
    }
    return f"""
    <html><head>
      <link rel="canonical" href="{public_url(item["id"], item["slug"])}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <div id="btn_online_application">
        <a href="{application_url or apply_url(item["id"], item["slug"])}">
          Jetzt bewerben!
        </a>
      </div>
    </body></html>
    """


def official_records() -> list[dict[str, str]]:
    return [
        record(
            "23412",
            title="SAP Architekt (m/w/d) 80-100%",
            slug="SAP-Architekt-mwd-80-100",
        ),
        record(
            "23508",
            title="Car Expert Skoda & CUPRA/SEAT (m/w/d) 80-100%",
            slug="Car-Expert-Skoda-CUPRASEAT-mwd-80-100",
            category="Automobil Berufe, Verkauf / Kundenberatung",
        ),
    ]


def test_amag_scans_complete_atom_catalog_and_enriches_details() -> None:
    records = official_records()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_atom(records), request=request)
        item = next(value for value in records if f"j{value['id']}.html" in request.url.path)
        kwargs = {"country": "LI", "city": "Gamprin-Bendern"} if item["id"] == "23508" else {}
        return httpx.Response(200, text=detail_html(item, **kwargs), request=request)

    result = AmagGroupJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 3
    assert str(requests[0].url) == FEED_URL
    assert result.message == ("Scanned 2 AMAG Group vacancies from the complete official catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "amag_group"
    assert first.title == "SAP Architekt (m/w/d) 80-100%"
    assert first.company == "AMAG Group"
    assert first.location == "Cham, Switzerland"
    assert first.url == public_url("23412", "SAP-Architekt-mwd-80-100")
    assert first.apply_url == apply_url("23412", "SAP-Architekt-mwd-80-100")
    assert first.posted_at == "2026-08-13"
    assert first.employment_type == "Full-time"
    assert first.description and "Gestalte die Mobilität" in first.description
    assert first.raw["category"] == "Informatik"
    assert first.raw["detail"]["schema"]["directApply"] is True
    assert result.jobs[1].location == "Gamprin-Bendern, Liechtenstein"


def test_amag_preserves_safe_feed_record_when_detail_fails() -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_atom([item]), request=request)
        return httpx.Response(503, text="temporarily unavailable", request=request)

    job = (
        AmagGroupJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.url == public_url("23412", "SAP-Architekt-mwd-80-100")
    assert job.apply_url == job.url
    assert job.location is None
    assert job.description and job.description.startswith("Wir bewegen")
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("detail_kwargs", "error_text"),
    [
        ({"title": "Different vacancy"}, "mismatched vacancy"),
        ({"country": "DE", "city": "Munich"}, "mismatched vacancy"),
        (
            {"application_url": "https://evil.example/apply/23412"},
            "mismatched vacancy",
        ),
    ],
)
def test_amag_rejects_untrusted_detail_but_keeps_feed_record(
    detail_kwargs: dict[str, str],
    error_text: str,
) -> None:
    item = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("rss_generator-rss0.php"):
            return httpx.Response(200, content=catalog_atom([item]), request=request)
        return httpx.Response(
            200,
            text=detail_html(item, **detail_kwargs),
            request=request,
        )

    job = (
        AmagGroupJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location is None
    assert error_text in str(job.raw["detail_error"])


def test_amag_rejects_duplicate_oversized_and_malformed_catalogs() -> None:
    item = official_records()[0]
    duplicate = catalog_atom([item, item])
    with pytest.raises(AmagGroupParseError, match="duplicate vacancy"):
        parse_catalog_atom(duplicate, base_url=BASE_URL, max_jobs=10)

    with pytest.raises(AmagGroupParseError, match="size is unexpected"):
        parse_catalog_atom(catalog_atom([item]), base_url=BASE_URL, max_jobs=0)

    unsafe = catalog_atom([item]).replace(
        b"https://jobs.amag.ch/",
        b"https://evil.example/",
    )
    with pytest.raises(AmagGroupParseError, match="incomplete or duplicate"):
        parse_catalog_atom(unsafe, base_url=BASE_URL, max_jobs=10)


def test_amag_wraps_feed_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    parser = AmagGroupJobsParser(transport=httpx.MockTransport(handler))
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_amag_is_registered_and_jobs_render_as_direct_company_imports() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["amag_group"]

    assert isinstance(parser, AmagGroupJobsParser)
    assert parser.base_url == settings.amag_group_jobs_base_url
    assert parser.feed_url == settings.amag_group_jobs_feed_url
    assert parser.max_jobs == settings.amag_group_jobs_max_jobs
    assert parser.detail_workers == settings.amag_group_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AMAG", "filters": {}},
            "sources": ["amag_group", "amag_group"],
        }
    )
    assert request.sources == ["amag_group"]

    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": "23412",
                "title": "SAP Architekt (m/w/d) 80-100%",
                "category": "Informatik",
                "url": public_url("23412", "SAP-Architekt-mwd-80-100"),
                "posted_at": "2026-08-13",
                "summary": "Gestalte die Mobilität von morgen.",
            },
            base_url=BASE_URL,
        ),
        job_id="amag_group-23412",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "AMAG Group import"
    assert stored["company"] == "AMAG Group"
