from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.infoguard import (
    InfoGuardJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.infoguard.test/en/career"


def listing_card(
    job_id: str,
    *,
    title: str,
    category: str = "Consultants",
    country: str = "switzerland",
    location: str = "Baar",
    workload: str = "80-100%",
    href: str | None = None,
) -> str:
    default_path = f"/de/karriere/de/{job_id}" if country == "germany" else f"/de/karriere/{job_id}"
    return f"""
    <a href="{href or default_path}">
      <div class="_job-row_abc_1" data-category="{category}"
           data-country="{country}">
        <div class="_job-row__info_abc_21">
          <div class="_job-row__category_abc_29">{category}</div>
          <div class="_job-row__title_abc_26">{title}</div>
        </div>
        <div class="_job-row__tags_abc_34">
          <div class="_label_abc_1">{location}</div>
          <div class="_label_abc_1">{workload}</div>
          <div class="_icon_abc_1"><svg></svg></div>
        </div>
      </div>
    </a>
    """


def listing_html(cards: list[str]) -> str:
    return f"""
    <html><body>
      <div class="jobs">
        <div class="_career-section__jobs_abc_25">{"".join(cards)}</div>
      </div>
    </body></html>
    """


def detail_html(
    job_id: str,
    *,
    title: str,
    location: str = "Baar",
    workload: str = "80-100%",
    apply_id: str = "1hz7pd7c",
    canonical_url: str | None = None,
) -> str:
    canonical = canonical_url or f"https://www.infoguard.test/de/karriere/{job_id}"
    return f"""
    <html>
      <head><link rel="canonical" href="{canonical}"></head>
      <body><div class="job_detail_main">
        <h1>{title}</h1>
        <div class="_hero-job__facts_abc_32">
          <div><p class="h4">{location}</p></div>
          <div><p class="h4">{workload}</p></div>
          <div><p class="h4">Hybrides Arbeiten</p></div>
          <div><p class="h4">Per sofort oder nach Vereinbarung</p></div>
        </div>
        <section>
          <h2>Dein Job</h2>
          <p>Cyber Security ist unsere Leidenschaft.</p>
          <div>Berate Unternehmen bei ihrer Sicherheitsstrategie.</div>
        </section>
        <section class="_job-skills_abc_1">
          <h3>Skill Check</h3>
          <div>Dein fachliches Profil</div>
          <div>Erfahrung mit ISO 27001.</div>
          <div>Dein persönliches Profil</div>
          <div>Analytisches und strukturiertes Denken.</div>
        </section>
        <a href="https://infoguard-ag.onlyfy.jobs/job/{apply_id}">
          Jetzt bewerben
        </a>
      </div></body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "cyber-security-consultant",
            title="Cyber Security Consultant",
        ),
        listing_card(
            "incident-responder",
            title="Incident Responder",
            category="Analysts &amp; Investigators",
        ),
        listing_card(
            "werkstudent-devops-monitoring-automation",
            title="Werkstudent DevOps / Monitoring &amp; Automation (m/w/d)",
            country="germany",
            location="Raum Frankfurt",
            workload="20h/Woche",
        ),
    ]


def test_infoguard_collects_full_swiss_catalog_and_enriches_every_vacancy() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/career":
            return httpx.Response(
                200,
                text=listing_html(catalog_fixture()),
                request=request,
            )
        job_id = request.url.path.rsplit("/", maxsplit=1)[-1]
        title = (
            "Cyber Security Consultant"
            if job_id == "cyber-security-consultant"
            else "Incident Responder"
        )
        apply_id = "1hz7pd7c" if job_id == "cyber-security-consultant" else "xc0na3j9"
        return httpx.Response(
            200,
            text=detail_html(job_id, title=title, apply_id=apply_id),
            request=request,
        )

    result = InfoGuardJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/en/career",
        "/de/karriere/cyber-security-consultant",
        "/de/karriere/incident-responder",
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 InfoGuard Switzerland vacancies from 3 official catalog records"
    )
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "infoguard"
    assert job.title == "Cyber Security Consultant"
    assert job.company == "InfoGuard AG"
    assert job.location == "Baar, Switzerland"
    assert job.url == ("https://www.infoguard.test/de/karriere/cyber-security-consultant")
    assert job.apply_url == "https://infoguard-ag.onlyfy.jobs/job/1hz7pd7c"
    assert job.posted_at is None
    assert job.employment_type == "80–100%"
    assert job.description == (
        "Dein Job\n\n"
        "Cyber Security ist unsere Leidenschaft.\n\n"
        "Berate Unternehmen bei ihrer Sicherheitsstrategie.\n\n"
        "Skill Check\n\n"
        "Dein fachliches Profil\n\n"
        "Erfahrung mit ISO 27001.\n\n"
        "Dein persönliches Profil\n\n"
        "Analytisches und strukturiertes Denken."
    )
    assert job.raw["detail"]["workplace_type"] == "Hybrides Arbeiten"
    assert job.raw["source_catalog_size"] == 3


def test_infoguard_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career":
            return httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "incident-responder",
                            title="Incident Responder",
                        )
                    ]
                ),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        InfoGuardJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Incident Responder"
    assert job.location == "Baar, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_infoguard_rejects_duplicate_non_swiss_or_unsafe_catalog_records() -> None:
    def parser_for(cards: list[str]) -> InfoGuardJobsParser:
        return InfoGuardJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(cards),
                    request=request,
                )
            ),
        )

    card = listing_card("incident-responder", title="Incident Responder")
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([card, card]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parser_for(
            [
                listing_card(
                    "incident-responder",
                    title="Incident Responder",
                    location="Berlin",
                )
            ]
        ).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy data"):
        parser_for(
            [
                listing_card(
                    "incident-responder",
                    title="Incident Responder",
                    href="https://evil.test/de/karriere/incident-responder",
                )
            ]
        ).search(LinkedInSearchRequest())


def test_infoguard_rejects_empty_catalog_and_mismatched_detail() -> None:
    empty = InfoGuardJobsParser(
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
                "incident-responder",
                title="Incident Responder",
                apply_id="invalid",
            ),
            page_url="https://www.infoguard.test/de/karriere/incident-responder",
            expected_url="https://www.infoguard.test/de/karriere/incident-responder",
            expected_job_id="incident-responder",
            expected_title="Incident Responder",
            expected_location="Baar",
            expected_workload="80–100%",
        )


def test_infoguard_wraps_listing_request_failures() -> None:
    parser = InfoGuardJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_infoguard_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["infoguard"]
    assert isinstance(parser, InfoGuardJobsParser)
    assert parser.base_url == settings.infoguard_jobs_base_url
    assert parser.detail_workers == settings.infoguard_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "InfoGuard", "filters": {}},
            "sources": ["infoguard", "infoguard"],
        }
    )
    assert request.sources == ["infoguard"]


def test_infoguard_jobs_render_as_direct_company_imports() -> None:
    job = InfoGuardJobsParser().normalize_job(
        {
            "id": "incident-responder",
            "title": "Incident Responder",
            "category": "Analysts & Investigators",
            "country": "switzerland",
            "location": "Baar",
            "workload": "80–100%",
            "url": "https://www.infoguard.ch/de/karriere/incident-responder",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="infoguard-incident-responder",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "InfoGuard import"
    assert stored["id"] == "infoguard-incident-responder"
