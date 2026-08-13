from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.hostpoint import (
    HostpointJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://hostpoint.test/en/jobs/"
UNITS = ("devs", "systems", "cc", "diverse", "admin", "lehrstelle")


def page_head(canonical: str, *, site_name: str = "Hostpoint") -> str:
    return f"""
    <head>
      <link rel="canonical" href="{canonical}">
      <meta property="og:site_name" content="{site_name}">
    </head>
    """


def listing_card(slug: str, title: str, workload: str, *, spontaneous: bool = False) -> str:
    special_class = " -spontan" if spontaneous else ""
    metadata = (
        f'<div class="spontan-data" data-slug="{slug}" data-remarks="4241046"></div>'
        if spontaneous
        else ""
    )
    return f"""
    <li class="job{special_class}">
      {metadata}
      <div class="header">
        <h5><a href="/en/jobs/details/{slug}/">{title}</a></h5><p>{workload}</p>
      </div>
    </li>
    """


def catalog_fixture() -> dict[str, list[str]]:
    return {
        "devs": [],
        "systems": [listing_card("system-engineer-unix", "System Engineer Unix", "80-100%")],
        "cc": [listing_card("it-supporter-deit", "IT Supporter (DE/IT)", "80-100%")],
        "diverse": [listing_card("spontanbewerbungen", "Spontanbewerbungen", "0%", spontaneous=True)],
        "admin": [],
        "lehrstelle": [
            listing_card(
                "lehrstelle-fachmann-fachfrau-ict",
                "Lehrstelle als ICT-Fachmann/-frau EFZ (2027)",
                "100%",
            )
        ],
    }


def listing_html(
    catalog: dict[str, list[str]],
    *,
    site_name: str = "Hostpoint",
    badge: str = "3",
) -> str:
    sections = "".join(
        f'<ul class="jobs-innerlist" data-unit="{unit}" data-count="8">'
        f'{"".join(catalog.get(unit, []))}</ul>'
        for unit in UNITS
    )
    return f"""
    <html lang="en">
      {page_head(BASE_URL, site_name=site_name)}
      <body class="jobsn allow-narrow en">
        <a href="/en/jobs/"><span class="bluepill">{badge}</span></a>
        <div id="jobs-list_"><div class="area-list">{sections}</div></div>
      </body>
    </html>
    """


def detail_html(
    slug: str,
    title: str,
    workload: str,
    *,
    internal_slug: str | None = None,
) -> str:
    return f"""
    <html lang="en">
      {page_head(f"https://hostpoint.test/jobs/details/{slug}/")}
      <body class="jobsd allow-narrow en">
        <div class="jobs-head" data-slug="{internal_slug or slug}">
          <h1 data-fulltitle="{title}">{title}</h1>
          <div class="flat-button -apply"><span>Jetzt bewerben!</span></div>
        </div>
        <div class="jobs-content-inner">
          <h2><span>Job-Portrait</span>{title}</h2>
          <ul class="jobs-params">
            <li class="-location"><b>Standort:</b> Rapperswil-Jona, Home-Office möglich</li>
            <li class="-employment"><b>Arbeitsverhältnis:</b> {workload}</li>
          </ul>
          <h3>Deine Aufgaben</h3>
          <p>Du betreibst zuverlässige Plattformen für unsere Kundinnen und Kunden.</p>
          <ul><li>Du arbeitest in einem erfahrenen Team.</li></ul>
        </div>
        <form class="apply-form"><input name="applicantLanguage" value="en"></form>
      </body>
    </html>
    """


def test_hostpoint_collects_complete_catalog_and_enriches_details() -> None:
    catalog = catalog_fixture()
    details = {
        "system-engineer-unix": ("System Engineer Unix", "80-100%"),
        "it-supporter-deit": ("IT Supporter (DE/IT)", "80-100%"),
        "spontanbewerbungen": ("Spontanbewerbungen", "0%"),
        "lehrstelle-fachmann-fachfrau-ict": (
            "Lehrstelle als ICT-Fachmann/-frau EFZ (2027)",
            "100%",
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=listing_html(catalog), request=request)
        slug = request.url.path.rstrip("/").split("/")[-1]
        title, workload = details[slug]
        return httpx.Response(
            200,
            text=detail_html(
                slug,
                title,
                workload,
                internal_slug="system-engineer-unix-neu" if slug == "system-engineer-unix" else slug,
            ),
            request=request,
        )

    result = HostpointJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 4 Hostpoint Switzerland vacancies from the official catalog"
    assert [job.title for job in result.jobs] == [
        "System Engineer Unix",
        "IT Supporter (DE/IT)",
        "Spontanbewerbungen",
        "Lehrstelle als ICT-Fachmann/-frau EFZ (2027)",
    ]
    first = result.jobs[0]
    assert first.source == "hostpoint"
    assert first.company == "Hostpoint AG"
    assert first.location == "Rapperswil-Jona, Switzerland"
    assert first.url == f"{BASE_URL}details/system-engineer-unix/"
    assert first.apply_url == first.url
    assert first.employment_type == "80–100%"
    assert first.description and "zuverlässige Plattformen" in first.description
    spontaneous = result.jobs[2]
    assert spontaneous.employment_type is None
    assert spontaneous.raw["spontaneous"] is True


def test_hostpoint_preserves_listing_when_detail_fails() -> None:
    catalog = {unit: [] for unit in UNITS}
    catalog["systems"] = [listing_card("system-engineer-unix", "System Engineer Unix", "80-100%")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=listing_html(catalog, badge="1"), request=request)
        return httpx.Response(503, request=request)

    job = HostpointJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]
    assert job.title == "System Engineer Unix"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_hostpoint_rejects_incomplete_duplicate_or_inconsistent_catalog() -> None:
    catalog = catalog_fixture()

    def run(page: str) -> None:
        HostpointJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    incomplete = dict(catalog)
    incomplete.pop("admin")
    with pytest.raises(DirectCompanyRequestError, match="complete vacancy catalog"):
        run(listing_html(incomplete).replace('data-unit="admin" data-count="8"', 'data-unit="other" data-count="8"'))
    duplicate = dict(catalog)
    duplicate["admin"] = list(catalog["systems"])
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        run(listing_html(duplicate))
    with pytest.raises(DirectCompanyRequestError, match="inconsistent vacancy count"):
        run(listing_html(catalog, badge="2"))


def test_hostpoint_rejects_wrong_identity_and_detail_contract() -> None:
    parser = HostpointJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), site_name="Attacker AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    detail_url = f"{BASE_URL}details/system-engineer-unix/"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html("system-engineer-unix", "Wrong title", "80-100%"),
            page_url=detail_url,
            expected_url=detail_url,
            expected_slug="system-engineer-unix",
            expected_title="System Engineer Unix",
            expected_workload="80-100%",
        )


def test_hostpoint_wraps_listing_request_failures() -> None:
    parser = HostpointJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_hostpoint_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["hostpoint"]
    assert isinstance(parser, HostpointJobsParser)
    assert parser.base_url == settings.hostpoint_jobs_base_url
    assert parser.detail_workers == settings.hostpoint_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "Hostpoint", "filters": {}}, "sources": ["hostpoint", "hostpoint"]}
    )
    assert request.sources == ["hostpoint"]

    job = normalize_job(
        {
            "id": "system-engineer-unix",
            "title": "System Engineer Unix",
            "url": "https://www.hostpoint.ch/en/jobs/details/system-engineer-unix/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="hostpoint-system-engineer-unix",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Hostpoint AG import"
    assert stored["id"] == "hostpoint-system-engineer-unix"
