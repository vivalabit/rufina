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
from app.services.parsers.companies.digital_architects_zurich import (
    DigitalArchitectsZurichJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://digital-architects-zurich.ch/career/"
LOGO_URL = (
    "https://digital-architects-zurich.ch/wp-content/uploads/2024/05/"
    "logo-DAZ-transparent-blau-weiss1.png"
)
JOBS = (
    (
        "CI/CD Engineer & Consultant",
        "https://digital-architects-zurich.ch/job-cicd-consultant/",
        (
            "https://join.com/companies/digital-architects-zurich/"
            "4538940-ci-cd-engineer-und-consultant"
        ),
        "2022-01-14T18:54:05+00:00",
    ),
    (
        "Observability & AIOps Engineer/Consultant",
        "https://digital-architects-zurich.ch/job-observability-aiops-engineer-consultant/",
        (
            "https://join.com/companies/digital-architects-zurich/"
            "4490086-observability-aiops-engineer-consultant"
        ),
        "2022-01-21T09:10:11+00:00",
    ),
    (
        "DevOps & Site Reliability Engineering Architect/Consultant",
        "https://digital-architects-zurich.ch/job-devops-sre-consultant/",
        (
            "https://join.com/companies/digital-architects-zurich/"
            "4434529-devops-engineer-und-site-reliability-engineer-architect-consultant"
        ),
        "2021-07-19T08:06:46+00:00",
    ),
)


def organization() -> dict[str, object]:
    return {
        "@type": "Organization",
        "name": "Digital Architects Zurich",
        "url": "https://digital-architects-zurich.ch/",
        "logo": {
            "@type": "ImageObject",
            "url": (
                "https://digital-architects-zurich.ch/wp-content/uploads/2020/11/blue-logo.jpg"
            ),
        },
    }


def listing_html() -> str:
    schema = {"@context": "https://schema.org", "@graph": [organization()]}
    cards = "".join(
        f"""
        <div class="et_pb_toggle_item">
          <h5 class="et_pb_toggle_title">{title}</h5>
          <div class="et_pb_toggle_content">
            <p>Exciting customer projects are waiting for you.</p>
            <a href="{httpx.URL(url).path}">Full Job Description</a>
          </div>
        </div>
        """
        for title, url, _, _ in JOBS
    )
    return f"""
    <html lang="en-US"><head>
      <link rel="canonical" href="{BASE_URL}">
      <meta property="og:url" content="{BASE_URL}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <div class="et_pb_section_0"><h1 class="et_pb_module_heading">Career</h1></div>
      <img src="{LOGO_URL}">
      <h1 class="et_pb_module_heading">Open Positions</h1>
      {cards}
      <footer>Digital Architects Zurich GmbH</footer>
    </body></html>
    """


def detail_html(
    *,
    title: str,
    url: str,
    apply_url: str,
    posted_at: str,
) -> str:
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "url": url,
                "inLanguage": "en-US",
                "datePublished": posted_at,
            },
            organization(),
        ],
    }
    return f"""
    <html lang="en-US"><head>
      <link rel="canonical" href="{url}">
      <meta property="og:url" content="{url}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <section class="et_pb_fullwidth_header">
        <h1 class="et_pb_module_header">{title}</h1>
        <span class="et_pb_fullwidth_header_subhead">Zurich, Basel, Berne / 80-100%</span>
        <a class="et_pb_button_one" href="{apply_url}">Apply Now</a>
      </section>
      <section class="et_pb_section_1">
        <h2>Fulltime Position</h2>
        <div class="et_pb_text_inner"><p>We are looking for expert consultants.</p></div>
        <h3>Job Description</h3>
        <div class="et_pb_text_inner"><ul><li>Shape projects from start to finish.</li></ul></div>
        <h3>Your Career</h3>
        <div class="et_pb_text_inner"><p>Develop cloud-native solutions.</p></div>
        <h3>Your Skills</h3>
        <div class="et_pb_text_inner"><ul><li>German and English skills.</li></ul></div>
        <a class="et_pb_button" href="{apply_url}">I'm Interested</a>
      </section>
      <footer>Digital Architects Zurich GmbH</footer>
    </body></html>
    """


def parser_with_catalog(*, detail_status: int = 200) -> DigitalArchitectsZurichJobsParser:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/career/":
            return httpx.Response(200, text=listing_html(), request=request)
        if request.url.host == "join.com" and request.method == "HEAD":
            return httpx.Response(200, request=request)
        item = next(
            (item for item in JOBS if httpx.URL(item[1]).path == request.url.path),
            None,
        )
        if item is None:
            return httpx.Response(404, request=request)
        if detail_status != 200:
            return httpx.Response(detail_status, request=request)
        title, url, apply_url, posted_at = item
        return httpx.Response(
            200,
            text=detail_html(
                title=title,
                url=url,
                apply_url=apply_url,
                posted_at=posted_at,
            ),
            request=request,
        )

    return DigitalArchitectsZurichJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )


def test_digital_architects_zurich_collects_and_enriches_complete_catalog() -> None:
    result = parser_with_catalog().search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Digital Architects Zurich vacancies from the official catalog"
    )
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "digital_architects_zurich"
    assert first.title == "CI/CD Engineer & Consultant"
    assert first.company == "Digital Architects Zurich GmbH"
    assert first.location == "Zürich / Basel / Bern, Switzerland"
    assert first.posted_at == "2022-01-14"
    assert first.employment_type == "Full-time / Part-time · 80–100%"
    assert "Shape projects from start to finish." in (first.description or "")
    assert first.apply_url == JOBS[0][2]
    assert result.jobs[-1].apply_url == JOBS[-1][2]


def test_digital_architects_zurich_preserves_catalog_when_details_fail() -> None:
    result = parser_with_catalog(detail_status=503).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert all(job.apply_url == job.url for job in result.jobs)
    assert all(job.posted_at is None for job in result.jobs)
    assert all("Exciting customer projects" in (job.description or "") for job in result.jobs)
    assert all("503 Service Unavailable" in job.raw["detail_error"] for job in result.jobs)


def test_digital_architects_zurich_rejects_wrong_identity_and_http_failures() -> None:
    parser = DigitalArchitectsZurichJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<html><title>Lookalike careers</title></html>",
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    parser = DigitalArchitectsZurichJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_digital_architects_zurich_rejects_incomplete_catalog_card() -> None:
    broken = listing_html().replace("Full Job Description", "Read more", 1)
    parser = DigitalArchitectsZurichJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=broken, request=request)
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_digital_architects_zurich_is_registered_and_stored_as_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["digital_architects_zurich"]
    assert isinstance(parser, DigitalArchitectsZurichJobsParser)
    assert parser.base_url == settings.digital_architects_zurich_jobs_base_url
    assert parser.detail_workers == settings.digital_architects_zurich_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Digital Architects Zurich", "filters": {}},
            "sources": ["digital_architects_zurich", "digital_architects_zurich"],
        }
    )
    assert request.sources == ["digital_architects_zurich"]

    job = normalize_job(
        {
            "id": "job-cicd-consultant",
            "title": "CI/CD Engineer & Consultant",
            "location": "Zürich / Basel / Bern, Switzerland",
            "workload": "80–100%",
            "url": JOBS[0][1],
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="digital_architects_zurich-job-cicd-consultant",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Digital Architects Zurich GmbH import"
    assert stored["id"] == "digital_architects_zurich-job-cicd-consultant"
