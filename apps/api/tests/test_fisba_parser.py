from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.fisba import FisbaJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(slug: str, *, title: str, location: str = "St. Gallen") -> str:
    return f"""
    <div class="job uk-flex">
      <div class="job__content__wrapper">
        <div class="views-field views-field-title">
          <span class="field-content">
            <a href="/en/jobs/{slug}"><h4>{title}</h4></a>
          </span>
        </div>
        <div class="views-field views-field-field-workplace-locality">
          <span class="views-label">Place of work</span>
          <span class="field-content">{location}</span>
        </div>
      </div>
    </div>
    """


def listing_html(
    vacancies: list[str],
    apprenticeships: list[str],
) -> str:
    return f"""
    <html><body><main>
      <div id="block-views-block-jobs-block-1--2">
        <h2>Open Vacancies</h2>
        <div class="view-content">{"".join(vacancies)}</div>
      </div>
      <div id="block-views-block-jobs-lehrlinge-block-1--2">
        <h2>Open Apprenticeships</h2>
        <div class="view-content">{"".join(apprenticeships)}</div>
      </div>
    </main></body></html>
    """


def detail_html(
    slug: str,
    *,
    title: str,
    application_path: str,
    contact: str = "Der Arbeitsort ist St. Gallen",
) -> str:
    return f"""
    <html><head>
      <link rel="canonical" href="https://www.fisba.test/en/jobs/{slug}">
    </head><body><main>
      <div class="jobs-full">
        <h1>{title}</h1>
        <div class="field--name-field-company-description">
          <p><strong>Give your job a new look</strong></p>
          <p>FISBA develops high-precision optical systems.</p>
        </div>
        <div class="field--name-body">
          <p><strong>Your responsibilities</strong></p>
          <ul><li>Build optical systems</li><li>Improve processes</li></ul>
        </div>
        <div class="field--name-field-job-requirements">
          <p><strong>Your profile</strong></p><p>Technical training.</p>
        </div>
        <div class="field--name-field-job-offer"><p>Modern workplace.</p></div>
        <div class="field--name-field-contact"><p>{contact}</p></div>
        <a class="jobs-button" href="{application_path}">Apply now</a>
      </div>
    </main></body></html>
    """


def test_fisba_collects_vacancies_and_apprenticeships_with_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/current-vacancies":
            return httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "einkaufer-100-mw",
                            title="Einkäufer 100% (m/w)",
                        )
                    ],
                    [
                        listing_card(
                            "lernender-konstrukteurin-efz-fur-2027",
                            title="Lernende/r: Konstrukteur/in EFZ für 2027",
                        )
                    ],
                ),
            )
        slug = request.url.path.rsplit("/", maxsplit=1)[-1]
        if slug == "einkaufer-100-mw":
            title = "Einkäufer 100% (m/w)"
            apply = (
                "https://fisba-job.abacuscity.ch/de/jobapplicationform"
                "?jobportal_id=3&jobportal_jobid=165020"
            )
        else:
            title = "Lernende/r: Konstrukteur/in EFZ für 2027"
            apply = (
                "https://fisba-job.abacuscity.ch/de/jobapplicationform"
                "?jobportal_id=3&jobportal_jobid=158500"
            )
        return httpx.Response(
            200,
            text=detail_html(
                slug,
                title=title,
                application_path=apply,
            ),
        )

    parser = FisbaJobsParser(
        base_url="https://www.fisba.test/en/current-vacancies",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert calls[0] == "/en/current-vacancies"
    assert set(calls[1:]) == {
        "/en/jobs/einkaufer-100-mw",
        "/en/jobs/lernender-konstrukteurin-efz-fur-2027",
    }
    assert result.status == "completed"
    assert result.message == ("Scanned 2 FISBA Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "fisba"
    assert first.title == "Einkäufer 100% (m/w)"
    assert first.company == "FISBA AG"
    assert first.location == "St. Gallen, Switzerland"
    assert first.url == "https://www.fisba.test/en/jobs/einkaufer-100-mw"
    assert first.apply_url == (
        "https://fisba-job.abacuscity.ch/de/jobapplicationform"
        "?jobportal_id=3&jobportal_jobid=165020"
    )
    assert first.posted_at is None
    assert first.employment_type == "100%"
    assert first.description and "Give your job a new look" in first.description
    assert first.description and "- Build optical systems" in first.description
    assert first.raw["catalog_section"] == "vacancy"
    assert first.raw["detail"]["id"] == "einkaufer-100-mw"
    assert result.jobs[1].employment_type == "Apprenticeship"
    assert result.jobs[1].raw["catalog_section"] == "apprenticeship"


def test_fisba_preserves_safe_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/current-vacancies":
            return httpx.Response(
                200,
                text=listing_html(
                    [listing_card("einkaufer-100-mw", title="Einkäufer 100% (m/w)")],
                    [],
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        FisbaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Einkäufer 100% (m/w)"
    assert job.company == "FISBA AG"
    assert job.location == "St. Gallen, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_fisba_rejects_malformed_or_non_swiss_catalog() -> None:
    malformed = FisbaJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )
    foreign = FisbaJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "optical-engineer",
                            title="Optical Engineer",
                            location="Berlin",
                        )
                    ],
                    [],
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy section"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        foreign.search(LinkedInSearchRequest())


def test_fisba_rejects_malformed_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/current-vacancies":
            return httpx.Response(
                200,
                text=listing_html(
                    [listing_card("optical-engineer", title="Optical Engineer")],
                    [],
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                "different-role",
                title="Different role",
                application_path=(
                    "https://fisba-job.abacuscity.ch/de/jobapplicationform?jobportal_jobid=1"
                ),
            ),
        )

    job = (
        FisbaJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Optical Engineer"
    assert "different vacancy" in str(job.raw["detail_error"])


def test_fisba_wraps_listing_request_failures() -> None:
    parser = FisbaJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_fisba_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["fisba"]
    assert isinstance(parser, FisbaJobsParser)
    assert parser.base_url == settings.fisba_jobs_base_url
    assert parser.detail_workers == settings.fisba_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "FISBA", "filters": {}},
            "sources": ["fisba", "fisba"],
        }
    )
    assert request.sources == ["fisba"]


def test_fisba_jobs_render_as_direct_company_imports() -> None:
    job = FisbaJobsParser().normalize_job(
        {
            "id": "einkaufer-100-mw",
            "title": "Einkäufer 100% (m/w)",
            "location": "St. Gallen",
            "catalog_section": "vacancy",
            "url": "https://www.fisba.com/en/jobs/einkaufer-100-mw",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="fisba-einkaufer-100-mw",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "www.fisba.com"
    assert stored["logo"] == "company"
    assert stored["department"] == "FISBA import"
    assert stored["id"] == "fisba-einkaufer-100-mw"
