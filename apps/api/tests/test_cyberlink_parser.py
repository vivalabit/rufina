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
from app.services.parsers.companies.cyberlink import CyberlinkJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(
    *,
    slug: str,
    title: str,
    workload: str,
    location: str = "Zürich Tiefenbrunnen",
) -> str:
    return f"""
    <div class="col-lg-12">
      <a href="https://cyberlink.digitalent.cloud/{slug}" target="_blank">
        <div class="card"><div class="card-body">
          <h3 class="gridFontTitle">{title}</h3>
          <div class="gridIconSetting">{workload}</div>
          <div class="gridIconSetting">{location}</div>
          <ul class="taglist"><li><span class="badge-tag">#IT</span></li></ul>
        </div></div>
      </a>
    </div>
    """


def listing_page(cards: list[str]) -> str:
    return f"""
    <html><body>
      <section class="jobboard-section"><div id="job-board">{"".join(cards)}</div></section>
      <div id="MCSDigitalentFooter">powered by digitalent</div>
    </body></html>
    """


def detail_page(
    *,
    slug: str,
    title: str,
    workload: str,
    country: str = "Schweiz",
    organization: str = "Cyberlink AG",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<h2>Was Dich erwartet.</h2><p>Arbeite an moderner ICT-Infrastruktur.</p>"
            "<h2>Was Du mitbringst.</h2><ul><li>Freude an Cloud-Technologien</li></ul>"
        ),
        "datePosted": "0001-01-01T00:00:00",
        "validThrough": "2026-10-29T14:15:38",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": organization,
        },
        "jobLocation": [
            {
                "@type": "Place",
                "address": [
                    {
                        "@type": "PostalAddress",
                        "addressCountry": country,
                        "addressLocality": "Zürich Tiefenbrunnen",
                    }
                ],
            }
        ],
    }
    form_id = "umbraco_form_3ea4a07b79d94c1c9332347f5f174838"
    return f"""
    <html><body>
      <nav id="navigation"><div id="meta-info">{workload}</div></nav>
      <section id="header"><h1>{title}</h1></section>
      <div id="contactModal">
        <div id="{form_id}"><form action="/{slug}" method="post"></form></div>
      </div>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_cyberlink_scans_complete_catalog_and_enriches_details() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/":
            assert request.url.host == "cyberlink.digitalent.cloud"
            assert request.headers["referer"] == (
                "https://www.cyberlink.ch/de/cyberlink/jobs"
            )
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            slug="informatikerin-efz-plattformentwicklung",
                            title="LEHRSTELLE Informatiker/in EFZ Plattformentwicklung",
                            workload="100 %",
                        ),
                        listing_card(
                            slug="spontanbewerbung",
                            title="Spontanbewerbung",
                            workload="80-100 %",
                        ),
                    ]
                ),
            )
        if request.url.path == "/informatikerin-efz-plattformentwicklung":
            return httpx.Response(
                200,
                text=detail_page(
                    slug="informatikerin-efz-plattformentwicklung",
                    title="LEHRSTELLE Informatiker/in EFZ Plattformentwicklung",
                    workload="100 %",
                ),
            )
        if request.url.path == "/spontanbewerbung":
            return httpx.Response(
                200,
                text=detail_page(
                    slug="spontanbewerbung",
                    title="Spontanbewerbung",
                    workload="80-100 %",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = CyberlinkJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Cyberlink vacancies from the complete Digitalent catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "cyberlink"
    assert first.title == "LEHRSTELLE Informatiker/in EFZ Plattformentwicklung"
    assert first.company == "Cyberlink AG"
    assert first.location == "Zürich Tiefenbrunnen, Schweiz"
    assert first.url == (
        "https://cyberlink.digitalent.cloud/"
        "informatikerin-efz-plattformentwicklung"
    )
    assert first.apply_url and first.apply_url.endswith("#contactModal")
    assert first.posted_at is None
    assert first.employment_type == "100 %, Full-time"
    assert first.description and "moderner ICT-Infrastruktur" in first.description
    assert first.description and "- Freude an Cloud-Technologien" in first.description
    assert first.raw["tags"] == ["#IT"]
    assert first.raw["detail"]["valid_through"] == "2026-10-29T14:15:38"


def test_cyberlink_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            slug="spontanbewerbung",
                            title="Spontanbewerbung",
                            workload="80-100 %",
                        )
                    ]
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        CyberlinkJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Spontanbewerbung"
    assert job.location == "Zürich Tiefenbrunnen"
    assert job.apply_url == "https://cyberlink.digitalent.cloud/spontanbewerbung"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_cyberlink_rejects_non_swiss_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            slug="spontanbewerbung",
                            title="Spontanbewerbung",
                            workload="80-100 %",
                        )
                    ]
                ),
            )
        return httpx.Response(
            200,
            text=detail_page(
                slug="spontanbewerbung",
                title="Spontanbewerbung",
                workload="80-100 %",
                country="Deutschland",
            ),
        )

    job = (
        CyberlinkJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Zürich Tiefenbrunnen"
    assert job.description is None
    assert "required vacancy data" in str(job.raw["detail_error"])


def test_cyberlink_rejects_incomplete_listing_card() -> None:
    page = listing_page(
        [
            listing_card(
                slug="spontanbewerbung",
                title="Spontanbewerbung",
                workload="",
            )
        ]
    )
    parser = CyberlinkJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_cyberlink_rejects_non_official_catalog_url() -> None:
    parser = CyberlinkJobsParser(
        catalog_url="https://example.test/jobs",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="")),
    )

    with pytest.raises(DirectCompanyRequestError, match="official job sources"):
        parser.search(LinkedInSearchRequest())


def test_cyberlink_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["cyberlink"]
    assert isinstance(parser, CyberlinkJobsParser)
    assert parser.base_url == settings.cyberlink_jobs_base_url
    assert parser.catalog_url == settings.cyberlink_jobs_catalog_url
    assert parser.detail_workers == settings.cyberlink_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Cyberlink", "filters": {}},
            "sources": ["cyberlink", "cyberlink"],
        }
    )
    assert request.sources == ["cyberlink"]


def test_cyberlink_jobs_render_as_direct_company_imports() -> None:
    parser = CyberlinkJobsParser()
    job = parser.normalize_job(
        {
            "id": "spontanbewerbung",
            "title": "Spontanbewerbung",
            "location": "Zürich Tiefenbrunnen",
            "url": "https://cyberlink.digitalent.cloud/spontanbewerbung",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="cyberlink-spontanbewerbung",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Cyberlink import"
    assert stored["id"] == "cyberlink-spontanbewerbung"
