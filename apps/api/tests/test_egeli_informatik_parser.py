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
from app.services.parsers.companies.egeli_informatik import (
    EgeliInformatikJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://egeli.test/karriere/"
PORTAL_URL = "https://jobs.dualoo.com/portal/lx0anfq4?lang=DE"
JOB_ONE = "d77b3af8-f9f7-45b4-9353-d85d64ae37e5"
JOB_TWO = "425b658c-a061-4c36-9d0f-0e9040f04237"


def career_html(*, site_name: str = "EGELI Informatik", portal_id: str = "lx0anfq4") -> str:
    return f"""
    <html lang="de-CH">
      <head>
        <link rel="canonical" href="{BASE_URL}">
        <meta property="og:site_name" content="{site_name}">
      </head>
      <body>
        <script id="dualoo-iframe-1">
          dualooIframe.addIframe({{
            elementId: 'dualoo-iframe-1',
            portalUrl: 'https://jobs.dualoo.com/portal/{portal_id}'
          }});
        </script>
      </body>
    </html>
    """


def portal_card(*, job_id: str, title: str, listing_location: str) -> str:
    return f"""
    <a class="row jobElement" href="lx0anfq4/{job_id}/detail?lang=DE">
      <span class="jobName">{title}</span>
      <span class="cityName">{listing_location}</span>
      <span class="jobDate" data-date="IMMEDIATELY">ab sofort</span>
    </a>
    """


def portal_html(cards: list[str], *, portal_id: str = "lx0anfq4") -> str:
    return f"""
    <html lang="de">
      <head><meta property="og:title" content="EGELI Informatik AG - Offene Stellen"></head>
      <body>
        <div class="JobInfoBox">{"".join(cards)}</div>
        <input id="jobPortalUrl" value="{portal_id}">
        <input id="lang" value="DE">
      </body>
    </html>
    """


def detail_url(job_id: str) -> str:
    return f"https://jobs.dualoo.com/portal/lx0anfq4/{job_id}/detail?lang=DE"


def detail_html(
    *,
    job_id: str,
    title: str,
    company: str,
    locality: str,
    country: str = "CH",
    apply_path: str = "apply?lang=DE",
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-05-29T06:12:57Z",
        "employmentType": ["PART_TIME", "FULL_TIME"],
        "description": "<p>Wir entwickeln clevere Schweizer Software-Lösungen.</p>",
        "responsibilities": "<ul><li>Du betreust moderne Plattformen.</li></ul>",
        "skills": "<p>Du bringst fundierte IT-Erfahrung mit.</p>",
        "jobBenefits": "<p>Flexible Arbeitszeiten und Weiterbildung.</p>",
        "directApply": True,
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": locality,
                "addressCountry": country,
            },
        },
    }
    return f"""
    <html lang="de">
      <head>
        <link rel="canonical" href="{detail_url(job_id)}">
        <meta property="og:title" content="{title}">
      </head>
      <body>
        <h1 class="jobName">{title}</h1>
        <a class="btn-apply" href="{apply_path}">Bewerben</a>
        <script type="application/ld+json">{json.dumps(schema)}</script>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        portal_card(
            job_id=JOB_ONE,
            title="Junior ICT System Engineer (m/w/d) 60-100%",
            listing_location="EGELI Informatik AG - St. Gallen",
        ),
        portal_card(
            job_id=JOB_TWO,
            title="Kundenbetreuer / Solution Specialist (m/w/d) 80-100%",
            listing_location="Xmatik AG - Arbon",
        ),
    ]


def test_egeli_collects_complete_portal_and_enriches_both_companies() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "egeli.test":
            return httpx.Response(200, text=career_html(), request=request)
        if request.url.path == "/portal/lx0anfq4":
            return httpx.Response(200, text=portal_html(catalog_fixture()), request=request)
        if request.url.path.endswith(f"/{JOB_ONE}/detail"):
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=JOB_ONE,
                    title="Junior ICT System Engineer (m/w/d) 60-100%",
                    company="EGELI Informatik AG",
                    locality="St. Gallen",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                job_id=JOB_TWO,
                title="Kundenbetreuer / Solution Specialist (m/w/d) 80-100%",
                company="Xmatik AG",
                locality="Arbon",
            ),
            request=request,
        )

    result = EgeliInformatikJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/karriere/",
        "/portal/lx0anfq4",
        f"/portal/lx0anfq4/{JOB_ONE}/detail",
        f"/portal/lx0anfq4/{JOB_TWO}/detail",
    ]
    assert result.message == (
        "Scanned 2 EGELI Informatik Switzerland vacancies from the official catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "egeli_informatik"
    assert first.title == "Junior ICT System Engineer (m/w/d) 60-100%"
    assert first.company == "EGELI Informatik AG"
    assert first.location == "St. Gallen, Switzerland"
    assert first.url == detail_url(JOB_ONE)
    assert first.apply_url == (f"https://jobs.dualoo.com/portal/lx0anfq4/{JOB_ONE}/apply?lang=DE")
    assert first.posted_at == "2026-05-29T06:12:57Z"
    assert first.employment_type == "60–100%"
    assert first.description and "- Du betreust moderne Plattformen" in first.description
    assert result.jobs[1].company == "Xmatik AG"
    assert result.jobs[1].location == "Arbon, Switzerland"
    assert result.jobs[1].employment_type == "80–100%"


def test_egeli_preserves_safe_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "egeli.test":
            return httpx.Response(200, text=career_html(), request=request)
        if request.url.path == "/portal/lx0anfq4":
            return httpx.Response(200, text=portal_html([catalog_fixture()[0]]), request=request)
        return httpx.Response(503, request=request)

    job = (
        EgeliInformatikJobsParser(base_url=BASE_URL, transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Junior ICT System Engineer (m/w/d) 60-100%"
    assert job.company == "EGELI Informatik AG"
    assert job.location == "St. Gallen, Switzerland"
    assert job.apply_url == job.url
    assert job.employment_type == "60–100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_egeli_rejects_wrong_career_or_portal_identity() -> None:
    def run(career: str, portal: str = "") -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=career if request.url.host == "egeli.test" else portal,
                request=request,
            )

        EgeliInformatikJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="invalid identity"):
        run(career_html(site_name="Attacker AG"))
    with pytest.raises(DirectCompanyRequestError, match="missing its job portal"):
        run(career_html(portal_id="attacker"))
    with pytest.raises(DirectCompanyRequestError, match="invalid identity"):
        run(career_html(), portal_html([], portal_id="wrong"))


def test_egeli_rejects_duplicate_catalog_and_untrusted_detail() -> None:
    card = catalog_fixture()[0]

    def duplicate_handler(request: httpx.Request) -> httpx.Response:
        text = career_html() if request.url.host == "egeli.test" else portal_html([card, card])
        return httpx.Response(200, text=text, request=request)

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        EgeliInformatikJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(duplicate_handler),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                title="Junior ICT System Engineer (m/w/d) 60-100%",
                company="Attacker AG",
                locality="St. Gallen",
                apply_path="https://attacker.example/apply",
            ),
            page_url=detail_url(JOB_ONE),
            expected_url=detail_url(JOB_ONE),
            expected_job_id=JOB_ONE,
            expected_title="Junior ICT System Engineer (m/w/d) 60-100%",
        )


def test_egeli_wraps_listing_request_failures() -> None:
    parser = EgeliInformatikJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_egeli_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["egeli_informatik"]
    assert isinstance(parser, EgeliInformatikJobsParser)
    assert parser.base_url == settings.egeli_informatik_jobs_base_url
    assert parser.portal_url == settings.egeli_informatik_jobs_portal_url
    assert parser.detail_workers == settings.egeli_informatik_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "EGELI", "filters": {}},
            "sources": ["egeli_informatik", "egeli_informatik"],
        }
    )
    assert request.sources == ["egeli_informatik"]


def test_egeli_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": JOB_ONE,
            "title": "Junior ICT System Engineer (m/w/d) 60-100%",
            "company": "EGELI Informatik AG",
            "location": "St. Gallen, Switzerland",
            "url": detail_url(JOB_ONE),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"egeli_informatik-{JOB_ONE}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "EGELI Informatik AG import"
    assert stored["id"] == f"egeli_informatik-{JOB_ONE}"
