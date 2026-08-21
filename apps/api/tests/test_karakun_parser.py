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
from app.services.parsers.companies.karakun import (
    KarakunJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://karakun.com/en/jobs/"
JOB_ONE = "fsse-en"
JOB_TWO = "full-stack-engineer-with-focus-on-artificial-intelligence-and-big-data-m-f"


def catalog_card(*, title: str, href: str, visible_title: str | None = None) -> str:
    return f"""
    <a class="k-overlay-link" title="{title}" href="{href}">
      <span class="k-title">{visible_title or title}</span>
      <span class="k-content"></span>
    </a>
    """


def catalog_html(
    cards: list[str],
    *,
    site_name: str = "Karakun AG",
    heading: str = "Open Positions at Karakun",
) -> str:
    return f"""
    <html lang="en-GB">
      <head>
        <link rel="canonical" href="{BASE_URL}">
        <meta property="og:site_name" content="{site_name}">
      </head>
      <body>
        <section id="page-content">
          <h2>{heading}</h2>
          {"".join(cards)}
          <a class="k-overlay-link" title="place to work" href="/about-us#great-place">
            <span class="k-title">place to work</span>
          </a>
          <a class="k-overlay-link" title="Privacy" href="/privacy-statement/">
            <span class="k-title">Privacy</span>
          </a>
        </section>
      </body>
    </html>
    """


def canonical_job_url(job_id: str) -> str:
    return f"https://karakun.com/en/jobs/{job_id}/"


def detail_html(
    *,
    job_id: str,
    title: str,
    company: str = "Karakun AG",
    canonical_id: str | None = None,
    apply_email: str = "hr@karakun.com",
) -> str:
    canonical = canonical_job_url(canonical_id or job_id)
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": f"{canonical}#webpage",
                "url": canonical,
                "name": f"{title} - Karakun AG",
                "datePublished": "2026-07-15T08:30:00+00:00",
                "dateModified": "2026-08-19T14:10:00+00:00",
            },
            {
                "@type": "Organization",
                "name": company,
                "url": "https://karakun.com/en/home-en/",
            },
        ],
    }
    return f"""
    <html lang="en-GB">
      <head>
        <link rel="canonical" href="{canonical}">
        <meta property="og:site_name" content="Karakun AG">
        <script type="application/ld+json">{json.dumps(schema)}</script>
      </head>
      <body>
        <section id="page-content">
          <h1>{title}</h1>
          <p>Karakun develops high-quality software solutions for demanding
             digitalisation projects from its home base in Basel.</p>
          <h3>Your responsibilities</h3>
          <ul>
            <li>Develop tailor-made software with modern Java and web technologies.</li>
            <li>Work with clients and an interdisciplinary engineering team.</li>
          </ul>
          <h3>What we offer</h3>
          <p>Flexible working, an education budget, central offices and the option
             to participate directly in Karakun's success.</p>
          <a href="mailto:{apply_email}?subject=Application%20{job_id}"
             aria-label="Apply for this job">Apply for this job</a>
          <style>.ignored {{ color: red; }}</style>
        </section>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        catalog_card(
            title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
            href=canonical_job_url(JOB_ONE),
        ),
        catalog_card(
            title="Full Stack Software Engineer with focus on AI and Big Data (m/f/d)",
            href=canonical_job_url(JOB_TWO),
        ),
        catalog_card(
            title="Speculative application",
            href="/jobs/speculative-application/",
        ),
    ]


def test_karakun_collects_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=catalog_html(catalog_fixture()), request=request)
        if request.url.path == "/jobs/speculative-application":
            return httpx.Response(
                301,
                headers={"Location": canonical_job_url("speculative-application")},
                request=request,
            )
        job_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        titles = {
            JOB_ONE: "Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
            JOB_TWO: "Full Stack Engineer with focus on AI and Big Data (m/f/d)",
            "speculative-application": "Speculative application",
        }
        return httpx.Response(
            200,
            text=detail_html(job_id=job_id, title=titles[job_id]),
            request=request,
        )

    result = KarakunJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/en/jobs/",
        f"/en/jobs/{JOB_ONE}",
        f"/en/jobs/{JOB_TWO}",
        "/jobs/speculative-application",
        "/en/jobs/speculative-application/",
    ]
    assert result.message == ("Scanned 3 Karakun vacancies from the complete official catalog")
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "karakun"
    assert first.title == "Full Stack Software Engineers for Java, Web and Mobile (m/f/d)"
    assert first.company == "Karakun AG"
    assert first.location == "Basel, Switzerland"
    assert first.url == canonical_job_url(JOB_ONE)
    assert first.apply_url == f"mailto:hr@karakun.com?subject=Application+{JOB_ONE}"
    assert first.posted_at == "2026-07-15T08:30:00+00:00"
    assert first.description and "- Develop tailor-made software" in first.description
    assert ".ignored" not in first.description
    assert result.jobs[1].title == "Full Stack Engineer with focus on AI and Big Data (m/f/d)"
    assert result.jobs[2].title == "Speculative application"
    assert all(job.description for job in result.jobs)


def test_karakun_follows_legacy_listing_redirect_to_canonical_detail() -> None:
    card = catalog_card(
        title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
        href="/fsse-en",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=catalog_html([card]), request=request)
        if request.url.path == "/fsse-en":
            return httpx.Response(
                301,
                headers={"Location": canonical_job_url(JOB_ONE)},
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                job_id=JOB_ONE,
                title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
            ),
            request=request,
        )

    job = (
        KarakunJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.url == canonical_job_url(JOB_ONE)
    assert job.apply_url and job.apply_url.startswith("mailto:hr@karakun.com")


def test_karakun_preserves_safe_listing_when_detail_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/jobs/":
            return httpx.Response(200, text=catalog_html([card]), request=request)
        return httpx.Response(503, request=request)

    job = (
        KarakunJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Full Stack Software Engineers for Java, Web and Mobile (m/f/d)"
    assert job.company == "Karakun AG"
    assert job.location == "Basel, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (catalog_html([], site_name="Attacker AG"), "invalid identity"),
        (catalog_html([], heading="Join our company"), "missing its vacancy catalog"),
        (
            catalog_html(
                [
                    catalog_card(
                        title="Software Engineer",
                        visible_title="Senior Software Engineer",
                        href=canonical_job_url("software-engineer"),
                    )
                ]
            ),
            "incomplete vacancy card",
        ),
    ],
)
def test_karakun_rejects_invalid_catalog(body: str, message: str) -> None:
    parser = KarakunJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_karakun_rejects_duplicates_and_catalog_over_limit() -> None:
    card = catalog_fixture()[0]

    def run(body: str, *, max_jobs: int = 100) -> None:
        KarakunJobsParser(
            max_jobs=max_jobs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=body, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        run(catalog_html([card, card]))
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        run(catalog_html(catalog_fixture()[:2]), max_jobs=1)


def test_karakun_rejects_untrusted_detail_page() -> None:
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
                company="Attacker AG",
                apply_email="jobs@attacker.example",
            ),
            page_url=canonical_job_url(JOB_ONE),
            expected_job_id=JOB_ONE,
            expected_title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
        )

    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                canonical_id="different-role",
                title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
            ),
            page_url=canonical_job_url("different-role"),
            expected_job_id=JOB_ONE,
            expected_title="Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
        )


def test_karakun_wraps_catalog_request_failures() -> None:
    parser = KarakunJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_karakun_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["karakun"]
    assert isinstance(parser, KarakunJobsParser)
    assert parser.base_url == settings.karakun_jobs_base_url
    assert parser.max_jobs == settings.karakun_jobs_max_jobs
    assert parser.detail_workers == settings.karakun_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Karakun", "filters": {}},
            "sources": ["karakun", "karakun"],
        }
    )
    assert request.sources == ["karakun"]


def test_karakun_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": JOB_ONE,
            "title": "Full Stack Software Engineers for Java, Web and Mobile (m/f/d)",
            "company": "Karakun AG",
            "location": "Basel, Switzerland",
            "url": canonical_job_url(JOB_ONE),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"karakun-{JOB_ONE}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Karakun AG import"
    assert stored["id"] == f"karakun-{JOB_ONE}"
