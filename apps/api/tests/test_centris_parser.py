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
from app.services.parsers.companies.centris import CentrisJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.centris.test/karriere/jobs"


def listing_card(
    job_id: str,
    *,
    title: str,
    posted_label: str = "online seit: 11.08.2026",
    listing_meta: str = "80 - 100% in Solothurn/Hybrid",
    href: str | None = None,
) -> str:
    return f"""
    <li>
      <a class="d-flex align-items-center justify-content-between"
         href="{href or f"https://www.centris.test/{job_id}"}">
        <div>
          <p class="small mb-1">{posted_label}</p>
          <h5 class="mb-1">{title}</h5>
          <p class="mb-0">{listing_meta}</p>
        </div>
      </a>
    </li>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><body><main>
      <div class="container-dynamic-content-joblist">
        <ul class="linklist medialist">{"".join(cards)}</ul>
      </div>
    </main></body></html>
    """


def detail_html(
    job_id: str,
    *,
    title: str,
    date_published: str = "2026-08-11T00:00:00+02:00",
    listing_meta: str = "80 - 100% in Solothurn/Hybrid",
    apply_job_id: str | None = None,
    schema_url: str | None = None,
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "datePublished": date_published,
                "name": title,
                "url": schema_url or f"https://www.centris.test/{job_id}",
            },
            {
                "@type": "Corporation",
                "name": "Centris AG",
                "url": "https://www.centrisag.ch/",
            },
        ],
    }
    application_id = apply_job_id or job_id
    return f"""
    <html><body>
      <header class="header-blog">
        <h1>{title}</h1>
        <p class="lead">{listing_meta}</p>
      </header>
      <main>
        <div class="container-headline"><h2>Starte mit Centris in die Zukunft</h2></div>
        <div class="container-text"><p>Gestalte die IT-Versicherungslandschaft.</p></div>
        <div class="container-factbox"><h2>Deine Aufgaben</h2></div>
        <div class="container-factbox">
          <h4>Was dich erwartet</h4>
          <div class="umantis"><ul>
            <li>Entwickle zuverlässige Plattformen.</li>
            <li>Arbeite mit internen Teams.</li>
          </ul></div>
        </div>
        <div class="container-factbox"><h2>Deine Skills</h2></div>
        <div class="container-factbox">
          <h4>Was du fachlich mitbringst</h4>
          <div class="umantis"><ul><li>Erfahrung mit Cloud-Systemen.</li></ul></div>
        </div>
        <div class="container-headline"><h2>Deine Benefits</h2></div>
        <div class="container-text"><p>Dieser Text gehört nicht zur Beschreibung.</p></div>
        <a class="button linkbutton"
           href="https://recruitingapp-2824.umantis.com/Vacancies/{application_id}/Application/CheckLogin/1?lang=ger">
          Jetzt bewerben
        </a>
      </main>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card("1085", title="Fachtester"),
        listing_card(
            "1092",
            title="DevOps Engineer Microsoft Infrastruktur &amp; Cloud Plattform",
            posted_label="online seit: 07.08.2026",
        ),
    ]


def test_centris_collects_full_catalog_and_enriches_every_vacancy() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/karriere/jobs":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        job_id = request.url.path.removeprefix("/")
        title = (
            "Fachtester"
            if job_id == "1085"
            else "DevOps Engineer Microsoft Infrastruktur & Cloud Plattform"
        )
        published = "2026-08-11T00:00:00+02:00" if job_id == "1085" else "2026-08-07T00:00:00+02:00"
        return httpx.Response(
            200,
            text=detail_html(job_id, title=title, date_published=published),
            request=request,
        )

    result = CentrisJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == ["/karriere/jobs", "/1085", "/1092"]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Centris Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "centris"
    assert job.title == "Fachtester"
    assert job.company == "Centris AG"
    assert job.location == "Solothurn/Hybrid, Switzerland"
    assert job.url == "https://www.centris.test/1085"
    assert job.apply_url == (
        "https://recruitingapp-2824.umantis.com/Vacancies/1085/Application/CheckLogin/1?lang=ger"
    )
    assert job.posted_at == "2026-08-11"
    assert job.employment_type == "80–100%"
    assert job.description == (
        "Starte mit Centris in die Zukunft\n\n"
        "Gestalte die IT-Versicherungslandschaft.\n\n"
        "Deine Aufgaben\n\nWas dich erwartet\n\n"
        "- Entwickle zuverlässige Plattformen.\n"
        "- Arbeite mit internen Teams.\n\n"
        "Deine Skills\n\nWas du fachlich mitbringst\n\n"
        "- Erfahrung mit Cloud-Systemen."
    )
    assert "Benefits" not in job.description
    assert job.raw["detail"]["id"] == "1085"
    assert result.jobs[1].title == ("DevOps Engineer Microsoft Infrastruktur & Cloud Plattform")


def test_centris_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/jobs":
            return httpx.Response(
                200,
                text=listing_html([listing_card("1085", title="Fachtester")]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        CentrisJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Fachtester"
    assert job.location == "Solothurn/Hybrid, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at == "2026-08-11"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_centris_rejects_duplicate_or_non_swiss_catalog_records() -> None:
    duplicate = listing_card("1085", title="Fachtester")
    duplicate_parser = CentrisJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([duplicate, duplicate]),
                request=request,
            )
        ),
    )
    non_swiss_parser = CentrisJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "1085",
                            title="Fachtester",
                            listing_meta="80 - 100% in Berlin/Hybrid",
                        )
                    ]
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate_parser.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        non_swiss_parser.search(LinkedInSearchRequest())


def test_centris_rejects_empty_catalog_and_mismatched_detail() -> None:
    empty = CentrisJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html/>", request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        empty.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html("1085", title="Fachtester", apply_job_id="9999"),
            page_url="https://www.centris.test/1085",
            expected_url="https://www.centris.test/1085",
            expected_job_id="1085",
            expected_title="Fachtester",
            expected_posted_at="2026-08-11",
            expected_listing_meta="80 - 100% in Solothurn/Hybrid",
        )


def test_centris_wraps_listing_request_failures() -> None:
    parser = CentrisJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_centris_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["centris"]
    assert isinstance(parser, CentrisJobsParser)
    assert parser.base_url == settings.centris_jobs_base_url
    assert parser.detail_workers == settings.centris_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Centris", "filters": {}},
            "sources": ["centris", "centris"],
        }
    )
    assert request.sources == ["centris"]


def test_centris_jobs_render_as_direct_company_imports() -> None:
    job = CentrisJobsParser().normalize_job(
        {
            "id": "1085",
            "title": "Fachtester",
            "posted_at": "2026-08-11",
            "workload": "80–100%",
            "location": "Solothurn/Hybrid",
            "url": "https://www.centrisag.ch/1085",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="centris-1085",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Centris import"
    assert stored["id"] == "centris-1085"
