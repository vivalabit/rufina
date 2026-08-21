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
from app.services.parsers.companies.hint_ag import (
    HintAgJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://hintag.ch/jobs/stellenangebote/"
PORTAL_URL = "https://jobs.dualoo.com/portal/t1jerlne?lang=DE"
JOB_ONE = "78ded90e-40e4-468e-8702-53698e58d2b3"
JOB_TWO = "573cb285-4732-4eb9-8b23-e8ae0ea7f12b"
INTERNAL_ONE = "f75110d3-14c4-4d79-aa56-79f46d5a52ec"
INTERNAL_TWO = "55ff0fc4-a6e4-42b3-9d29-a10b552bc124"


def career_html(
    *,
    site_name: str = "HINT AG",
    portal_id: str = "t1jerlne",
    spontaneous_id: str = "d1d9bb61-5b5e-4ef0-afb6-939a38782679",
) -> str:
    return f"""
    <html lang="de-DE"><head><title>Stellenangebote - HINT AG</title>
      <link rel="canonical" href="{BASE_URL}">
      <link rel="preload" as="image"
            href="https://hintag.ch/wp-content/uploads/2022/08/hintag-lenzburg-1.svg">
      <meta property="og:site_name" content="{site_name}">
    </head><body><h1 class="elementor-heading-title">Jobs &amp; Karriere</h1>
      <h1 class="elementor-heading-title">
      Unsere Fachkräfte sind unsere Zukunft</h1>
      <script id="dualoo-iframe-1">
        dualooIframe.addIframe({{
          elementId: 'dualoo-iframe-1',
          portalUrl: 'https://jobs.dualoo.com/portal/{portal_id}'
        }});
      </script>
      <a href="https://jobs.dualoo.com/link/{spontaneous_id}/apply?lang=DE">
        Spontanbewerbung</a>
    </body></html>
    """


def detail_url(job_id: str) -> str:
    return f"https://jobs.dualoo.com/portal/t1jerlne/{job_id}/detail?lang=DE"


def apply_url(job_id: str) -> str:
    return f"https://jobs.dualoo.com/portal/t1jerlne/{job_id}/apply?lang=DE"


def portal_card(*, job_id: str, title: str) -> str:
    return f"""
    <a class="row jobElement" href="t1jerlne/{job_id}/detail?lang=DE">
      <span class="jobName">{title}</span>
      <span class="cityName">HINT AG - Lenzburg</span>
      <span class="jobDate" data-date="IMMEDIATELY">ab sofort</span>
    </a>
    """


def portal_html(cards: list[str], *, portal_id: str = "t1jerlne") -> str:
    return f"""
    <html lang="de"><head>
      <meta property="og:title" content="HINT AG - Offene Stellen">
    </head><body><div class="JobInfoBox">{"".join(cards)}</div>
      <input id="jobPortalUrl" value="{portal_id}">
      <input id="lang" value="DE">
    </body></html>
    """


def catalog_fixture() -> list[str]:
    return [
        portal_card(
            job_id=JOB_ONE,
            title="Customer Solution Manager (CSM) (m/w/d) 80-100%",
        ),
        portal_card(
            job_id=JOB_TWO,
            title="Senior Key Account Manager (m/w/d) 80-100%",
        ),
    ]


def detail_html(
    *,
    job_id: str,
    internal_id: str,
    title: str,
    company: str = "HINT AG",
    locality: str = "Lenzburg",
    country: str = "CH",
    apply_path: str = "apply?lang=DE",
    canonical_portal: str = "u8vvao5q",
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-08-07T14:34:46Z",
        "employmentType": ["PART_TIME", "FULL_TIME"],
        "description": (
            "<p>Wir decken die ICT-Bedürfnisse der Schweizer Spitäler, "
            "Heime und Praxen mit sicheren digitalen Lösungen ab.</p>"
        ),
        "responsibilities": (
            "<p><b>Deine Aufgaben</b></p><ul><li>Du analysierst "
            "Kundenbedürfnisse und konzipierst tragfähige Lösungen.</li></ul>"
        ),
        "skills": (
            "<p><b>Dein Profil</b></p><ul><li>Du bringst fundierte "
            "Erfahrung in kundenorientierten IT-Rollen mit.</li></ul>"
        ),
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
    canonical = (
        f"https://jobs.dualoo.com/portal/{canonical_portal}/{internal_id}/"
        "detail?lang=DE"
    )
    return f"""
    <html lang="de"><head><link rel="canonical" href="{canonical}">
      <meta property="og:title" content="{title}">
    </head><body><h1 class="jobName">{title}</h1>
      <span class="cityName">HINT AG - Lenzburg</span>
      <span id="contactOneCompany">{company}</span>
      <a class="btn-apply" href="{apply_path}">Bewerben</a>
      <input id="jobPortalUrl" value="t1jerlne">
      <input id="lang" value="DE">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_hint_ag_collects_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "hintag.ch":
            return httpx.Response(200, text=career_html(), request=request)
        if request.url.path == "/portal/t1jerlne":
            return httpx.Response(
                200,
                text=portal_html(catalog_fixture()),
                request=request,
            )
        if request.url.path.endswith(f"/{JOB_ONE}/detail"):
            content = detail_html(
                job_id=JOB_ONE,
                internal_id=INTERNAL_ONE,
                title="Customer Solution Manager (CSM) (m/w/d) 80-100%",
            )
        else:
            content = detail_html(
                job_id=JOB_TWO,
                internal_id=INTERNAL_TWO,
                title="Senior Key Account Manager (m/w/d) 80-100%",
            )
        return httpx.Response(200, text=content, request=request)

    result = HintAgJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [BASE_URL, PORTAL_URL, detail_url(JOB_ONE), detail_url(JOB_TWO)]
    assert result.message == (
        "Scanned 2 HINT AG vacancies from the complete official Dualoo catalog"
    )
    assert len(result.jobs) == 2
    job = result.jobs[0]
    assert job.source == "hint_ag"
    assert job.title == "Customer Solution Manager (CSM) (m/w/d) 80-100%"
    assert job.company == "HINT AG"
    assert job.location == "Lenzburg, Switzerland"
    assert job.url == detail_url(JOB_ONE)
    assert job.apply_url == apply_url(JOB_ONE)
    assert job.posted_at == "2026-08-07T14:34:46Z"
    assert job.employment_type == "80–100%"
    assert job.description and "- Du analysierst Kundenbedürfnisse" in job.description
    assert job.raw["catalog_index"] == 0
    assert job.raw["detail"]["canonical_job_id"] == INTERNAL_ONE


def test_hint_ag_preserves_verified_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hintag.ch":
            return httpx.Response(200, text=career_html(), request=request)
        if request.url.path == "/portal/t1jerlne":
            return httpx.Response(
                200,
                text=portal_html([catalog_fixture()[0]]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        HintAgJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Customer Solution Manager (CSM) (m/w/d) 80-100%"
    assert job.company == "HINT AG"
    assert job.location == "Lenzburg, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("career", "message"),
    [
        (career_html(site_name="Attacker AG"), "invalid identity"),
        (career_html(portal_id="attacker"), "official job portal"),
        (career_html(spontaneous_id=JOB_ONE), "official job portal"),
    ],
)
def test_hint_ag_rejects_untrusted_parent_page(career: str, message: str) -> None:
    parser = HintAgJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=career, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_hint_ag_rejects_bad_portal_identity_and_duplicate_catalog() -> None:
    def parser_for(portal: str) -> HintAgJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            content = career_html() if request.url.host == "hintag.ch" else portal
            return httpx.Response(200, text=content, request=request)

        return HintAgJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="invalid identity"):
        parser_for(portal_html([], portal_id="wrong")).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy"):
        parser_for(portal_html([catalog_fixture()[0]] * 2)).search(
            LinkedInSearchRequest()
        )


def test_hint_ag_accepts_empty_catalog_and_enforces_job_limit() -> None:
    def parser_for(portal: str, *, max_jobs: int = 100) -> HintAgJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            content = career_html() if request.url.host == "hintag.ch" else portal
            return httpx.Response(200, text=content, request=request)

        return HintAgJobsParser(
            max_jobs=max_jobs,
            transport=httpx.MockTransport(handler),
        )

    result = parser_for(portal_html([])).search(LinkedInSearchRequest())
    assert result.jobs == []
    assert result.message.startswith("Scanned 0 HINT AG vacancies")

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser_for(portal_html(catalog_fixture()), max_jobs=1).search(
            LinkedInSearchRequest()
        )


def test_hint_ag_rejects_untrusted_detail_but_keeps_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "hintag.ch":
            content = career_html()
        elif request.url.path == "/portal/t1jerlne":
            content = portal_html([catalog_fixture()[0]])
        else:
            content = detail_html(
                job_id=JOB_ONE,
                internal_id=INTERNAL_ONE,
                title="Customer Solution Manager (CSM) (m/w/d) 80-100%",
                company="Attacker AG",
                apply_path="https://attacker.example/apply",
            )
        return httpx.Response(200, text=content, request=request)

    job = (
        HintAgJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.description is None
    assert "incomplete vacancy" in str(job.raw["detail_error"])

    with pytest.raises(DirectCompanyRequestError, match="invalid identity"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                internal_id=INTERNAL_ONE,
                title="Customer Solution Manager (CSM) (m/w/d) 80-100%",
                canonical_portal="invalid-portal",
            ),
            page_url=detail_url(JOB_ONE),
            expected_record={
                "id": JOB_ONE,
                "title": "Customer Solution Manager (CSM) (m/w/d) 80-100%",
                "url": detail_url(JOB_ONE),
            },
        )


def test_hint_ag_wraps_http_errors() -> None:
    parser = HintAgJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_hint_ag_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["hint_ag"]
    assert isinstance(parser, HintAgJobsParser)
    assert parser.base_url == settings.hint_ag_jobs_base_url
    assert parser.portal_url == settings.hint_ag_jobs_portal_url
    assert parser.max_jobs == settings.hint_ag_jobs_max_jobs
    assert parser.detail_workers == settings.hint_ag_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "HINT AG", "filters": {}},
            "sources": ["hint_ag", "hint_ag"],
        }
    )
    assert request.sources == ["hint_ag"]


def test_hint_ag_jobs_render_as_direct_company_imports() -> None:
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": JOB_ONE,
                "title": "Customer Solution Manager (CSM) (m/w/d) 80-100%",
                "company": "HINT AG",
                "location": "Lenzburg, Switzerland",
                "url": detail_url(JOB_ONE),
            }
        ),
        job_id=f"hint_ag-{JOB_ONE}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "HINT AG import"
    assert stored["company"] == "HINT AG"
    assert stored["id"] == f"hint_ag-{JOB_ONE}"
