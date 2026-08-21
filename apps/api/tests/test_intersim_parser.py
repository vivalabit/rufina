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
from app.services.parsers.companies.intersim import (
    IntersimJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

PORTAL_URL = "https://jobs.dualoo.com/portal/dlpdkskq?lang=DE"
JOB_ONE = "b69eec5b-cd89-4dcf-a304-9a23429003ee"
JOB_TWO = "3dae4a83-3bbc-4993-b678-4f95d1900bf6"


def portal_card(
    *,
    job_id: str,
    title: str,
    location: str = "Intersim AG - Burgdorf",
    category: str = "Mitarbeitende",
) -> str:
    return f"""
    <a class="row jobElement" href="dlpdkskq/{job_id}/detail?lang=DE">
      <span class="jobName">{title}</span>
      <span class="cityName">{location}</span>
      <span class="jobCategory">{category}</span>
      <span class="jobDate" data-date="AGREEMENT">nach Vereinbarung</span>
    </a>
    """


def portal_html(
    cards: list[str],
    *,
    portal_id: str = "dlpdkskq",
    title: str = "Intersim AG - Offene Stellen",
) -> str:
    return f"""
    <html lang="de">
      <head><meta property="og:title" content="{title}"></head>
      <body>
        <div class="JobInfoBox">{"".join(cards)}</div>
        <input id="jobPortalUrl" value="{portal_id}">
        <input id="lang" value="DE">
      </body>
    </html>
    """


def detail_url(job_id: str) -> str:
    return f"https://jobs.dualoo.com/portal/dlpdkskq/{job_id}/detail?lang=DE"


def public_url(job_id: str) -> str:
    return f"https://www.intersim.ch/jobs/{job_id}"


def detail_html(
    *,
    job_id: str,
    title: str,
    company: str = "Intersim AG",
    locality: str = "Burgdorf",
    country: str = "CH",
    apply_path: str = "apply?lang=DE",
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "datePosted": "2026-08-07T12:02:47Z",
        "employmentType": ["PART_TIME", "FULL_TIME"],
        "description": "<p>Wir entwickeln nachhaltige digitale Lösungen.</p>",
        "responsibilities": "<ul><li>Du entwickelst moderne Webanwendungen.</li></ul>",
        "skills": "<p>Du bringst fundierte Erfahrung in der Softwareentwicklung mit.</p>",
        "jobBenefits": "<p>Flexibles Arbeiten und gezielte Weiterbildung.</p>",
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
      <head><link rel="canonical" href="{detail_url(job_id)}"></head>
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
            title="Senior Fullstack Entwickler:in / Teamleader:in 80-100%",
        ),
        portal_card(
            job_id=JOB_TWO,
            title="Fullstack Entwickler:in .NET 60-100%",
        ),
    ]


def test_intersim_collects_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/portal/dlpdkskq":
            return httpx.Response(200, text=portal_html(catalog_fixture()), request=request)
        if request.url.path.endswith(f"/{JOB_ONE}/detail"):
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=JOB_ONE,
                    title="Senior Fullstack Entwickler:in / Teamleader:in 80-100%",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                job_id=JOB_TWO,
                title="Fullstack Entwickler:in .NET 60-100%",
            ),
            request=request,
        )

    result = IntersimJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/portal/dlpdkskq",
        f"/portal/dlpdkskq/{JOB_ONE}/detail",
        f"/portal/dlpdkskq/{JOB_TWO}/detail",
    ]
    assert result.message == (
        "Scanned 2 Intersim vacancies from the complete official Dualoo catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "intersim"
    assert first.title == "Senior Fullstack Entwickler:in / Teamleader:in"
    assert first.company == "Intersim AG"
    assert first.location == "Burgdorf, Switzerland"
    assert first.url == public_url(JOB_ONE)
    assert first.apply_url == (f"https://jobs.dualoo.com/portal/dlpdkskq/{JOB_ONE}/apply?lang=DE")
    assert first.posted_at == "2026-08-07T12:02:47Z"
    assert first.employment_type == "80–100%"
    assert first.seniority == "Senior"
    assert first.description and "- Du entwickelst moderne Webanwendungen" in first.description
    assert result.jobs[1].title == "Fullstack Entwickler:in .NET"
    assert result.jobs[1].employment_type == "60–100%"


def test_intersim_preserves_safe_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/portal/dlpdkskq":
            return httpx.Response(
                200,
                text=portal_html([catalog_fixture()[0]]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        IntersimJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Fullstack Entwickler:in / Teamleader:in"
    assert job.company == "Intersim AG"
    assert job.location == "Burgdorf, Switzerland"
    assert job.url == public_url(JOB_ONE)
    assert job.apply_url == job.url
    assert job.employment_type == "80–100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (portal_html([], title="Attacker AG - Offene Stellen"), "invalid identity"),
        (portal_html([], portal_id="wrong"), "invalid identity"),
        (
            portal_html(
                [
                    portal_card(
                        job_id=JOB_ONE,
                        title="Fullstack Entwickler:in 80-100%",
                        location="Attacker AG - Berlin",
                    )
                ]
            ),
            "invalid vacancy",
        ),
    ],
)
def test_intersim_rejects_wrong_portal_identity_or_scope(body: str, message: str) -> None:
    parser = IntersimJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_intersim_rejects_duplicate_catalog_and_configured_overflow() -> None:
    card = catalog_fixture()[0]

    def run(cards: list[str], *, max_jobs: int = 100) -> None:
        IntersimJobsParser(
            max_jobs=max_jobs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=portal_html(cards),
                    request=request,
                )
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        run([card, card])
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        run(catalog_fixture(), max_jobs=1)


def test_intersim_accepts_a_verified_empty_catalog() -> None:
    result = IntersimJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=portal_html([]),
                request=request,
            )
        )
    ).search(LinkedInSearchRequest())

    assert result.status == "completed"
    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Intersim vacancies from the complete official Dualoo catalog"
    )


def test_intersim_rejects_untrusted_or_incomplete_detail() -> None:
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                title="Senior Fullstack Entwickler:in / Teamleader:in 80-100%",
                company="Attacker AG",
                apply_path="https://attacker.example/apply",
            ),
            page_url=detail_url(JOB_ONE),
            expected_url=detail_url(JOB_ONE),
            expected_job_id=JOB_ONE,
            expected_portal_title=("Senior Fullstack Entwickler:in / Teamleader:in 80-100%"),
        )


def test_intersim_wraps_listing_request_failures() -> None:
    parser = IntersimJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_intersim_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["intersim"]
    assert isinstance(parser, IntersimJobsParser)
    assert parser.base_url == settings.intersim_jobs_base_url
    assert parser.portal_url == settings.intersim_jobs_portal_url
    assert parser.max_jobs == settings.intersim_jobs_max_jobs
    assert parser.detail_workers == settings.intersim_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Intersim", "filters": {}},
            "sources": ["intersim", "intersim"],
        }
    )
    assert request.sources == ["intersim"]


def test_intersim_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": JOB_ONE,
            "title": "Senior Fullstack Entwickler:in / Teamleader:in",
            "company": "Intersim AG",
            "location": "Burgdorf, Switzerland",
            "url": public_url(JOB_ONE),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"intersim-{JOB_ONE}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Intersim AG import"
    assert stored["id"] == f"intersim-{JOB_ONE}"
