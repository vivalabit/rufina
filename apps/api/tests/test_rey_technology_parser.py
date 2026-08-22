from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.rey_technology import (
    REY_APPLICATION_URL,
    ReyTechnologyJobsParser,
    normalize_job,
    parse_detail_html,
    parse_listing_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.rey-technology.com/en/career/vacancies/"
SERVICE_SLUG = "software-engineer-service-mfd"
UNSOLICITED_SLUG = "unsolicited-application"


def job_url(slug: str) -> str:
    return f"{BASE_URL}position/{slug}/"


def page_head(
    *,
    canonical: str,
    site_name: str = "Rey Technology",
) -> str:
    return f"""
    <head>
      <title>Vacancies | Rey Technology</title>
      <link rel="canonical" href="{canonical}">
      <meta property="og:site_name" content="{site_name}">
    </head>
    """


def vacancy_card(
    *,
    slug: str,
    title: str,
    location: str,
    workload: str,
    start: str = "by arrangement",
    href: str | None = None,
) -> str:
    return f"""
    <li class="c-jobs-list__item">
      <div class="c-jobs-teaser">
        <div class="c-jobs-teaser__title"><h3>{title}</h3></div>
        <div class="c-jobs-teaser__place"><span>{location}</span></div>
        <div class="c-jobs-teaser__workload"><span>{workload}</span></div>
        <div class="c-jobs-teaser__start"><span>{start}</span></div>
        <a class="u-cover-object" href="{href or job_url(slug)}">Read more</a>
      </div>
    </li>
    """


def official_cards() -> list[str]:
    return [
        vacancy_card(
            slug=SERVICE_SLUG,
            title="Software Engineer Service (m/f/d)",
            location="Sirnach or Arlesheim",
            workload="100 %",
        ),
        vacancy_card(
            slug=UNSOLICITED_SLUG,
            title="Unsolicited application",
            location="Sirnach | Arlesheim | Freiburg",
            workload="",
        ),
    ]


def listing_html(
    cards: list[str] | None = None,
    *,
    canonical: str = BASE_URL,
    site_name: str = "Rey Technology",
    heading: str = "Vacancies",
) -> str:
    return f"""
    <html lang="en-CH">
      {page_head(canonical=canonical, site_name=site_name)}
      <body>
        <main id="main">
          <h1>{heading}</h1>
          <h2>Vacancies</h2>
          <ul class="c-jobs-list__items">{"".join(cards or official_cards())}</ul>
        </main>
      </body>
    </html>
    """


def detail_html(
    *,
    slug: str,
    title: str,
    location: str,
    workload: str,
    start: str = "by arrangement",
    canonical: str | None = None,
    apply_url: str = REY_APPLICATION_URL,
) -> str:
    return f"""
    <html lang="en-CH">
      {page_head(canonical=canonical or job_url(slug))}
      <body>
        <div class="c-jobs-detail">
          <div class="c-jobs-detail__lead-infos">
            <div class="c-jobs-detail__place"><span>Location: {location}</span></div>
            <div class="c-jobs-detail__workload"><span>Workload: {workload}</span></div>
            <div class="c-jobs-detail__start"><span>Start: {start}</span></div>
          </div>
          <div class="c-jobs-detail__title"><h1>{title}</h1></div>
          <div class="c-jobs-detail__text">
            <div class="c-richtext">
              <h3>Your responsibilities</h3>
              <ul>
                <li>Programming corrections, optimizations, and enhancements.</li>
                <li>Supporting customers and coordinating with the project team.</li>
              </ul>
              <h3>Your profile</h3>
              <p>You work independently, communicate clearly, and understand
                 complex technical systems in an industrial environment.</p>
              <h3>What to expect</h3>
              <p>Flexible working hours, modern workplaces, professional growth,
                 and a team that works together and supports each other.</p>
            </div>
          </div>
          <div class="c-jobs-detail__cta">
            <a href="{apply_url}">Apply online now</a>
          </div>
        </div>
      </body>
    </html>
    """


def details_by_slug() -> dict[str, str]:
    return {
        SERVICE_SLUG: detail_html(
            slug=SERVICE_SLUG,
            title="Software Engineer Service (m/f/d)",
            location="Sirnach or Arlesheim",
            workload="100 %",
        ),
        UNSOLICITED_SLUG: detail_html(
            slug=UNSOLICITED_SLUG,
            title="Unsolicited application",
            location="Sirnach | Arlesheim | Freiburg",
            workload="",
        ),
    }


def test_rey_scans_complete_catalog_and_enriches_details() -> None:
    calls: list[str] = []
    details = details_by_slug()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/career/vacancies/":
            return httpx.Response(200, text=listing_html(), request=request)
        slug = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(200, text=details[slug], request=request)

    result = ReyTechnologyJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/en/career/vacancies/",
        f"/en/career/vacancies/position/{SERVICE_SLUG}/",
        f"/en/career/vacancies/position/{UNSOLICITED_SLUG}/",
    ]
    assert result.message == (
        "Scanned 2 Rey Technology vacancies from the complete visible official "
        "careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "rey_technology"
    assert first.title == "Software Engineer Service (m/f/d)"
    assert first.company == "Rey Technology"
    assert first.location == "Sirnach or Arlesheim, Switzerland"
    assert first.url == job_url(SERVICE_SLUG)
    assert first.apply_url == REY_APPLICATION_URL
    assert first.employment_type == "100%"
    assert first.description and "Your responsibilities" in first.description
    assert "- Programming corrections" in first.description
    assert first.raw["catalog_index"] == 0

    unsolicited = result.jobs[1]
    assert unsolicited.employment_type is None
    assert unsolicited.location == (
        "Sirnach | Arlesheim | Freiburg, Switzerland / Germany"
    )


def test_rey_preserves_verified_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career/vacancies/":
            return httpx.Response(
                200,
                text=listing_html(official_cards()[:1]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        ReyTechnologyJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Software Engineer Service (m/f/d)"
    assert job.location == "Sirnach or Arlesheim, Switzerland"
    assert job.apply_url == REY_APPLICATION_URL
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (listing_html(site_name="Other AG"), "invalid identity"),
        (listing_html(heading="Career opportunities"), "vacancy catalog"),
        (
            listing_html(
                [
                    vacancy_card(
                        slug=SERVICE_SLUG,
                        title="Software Engineer Service (m/f/d)",
                        location="Sirnach",
                        workload="full time",
                    )
                ]
            ),
            "incomplete vacancy",
        ),
    ],
)
def test_rey_rejects_malformed_or_untrusted_catalogs(
    body: str,
    message: str,
) -> None:
    with pytest.raises(DirectCompanyRequestError, match=message):
        parse_listing_html(
            body,
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )


def test_rey_rejects_unsafe_duplicate_and_oversized_catalogs() -> None:
    unsafe = vacancy_card(
        slug=SERVICE_SLUG,
        title="Software Engineer Service (m/f/d)",
        location="Sirnach",
        workload="100%",
        href="https://attacker.example/jobs/software-engineer",
    )
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_listing_html(
            listing_html([unsafe]),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        parse_listing_html(
            listing_html([official_cards()[0], official_cards()[0]]),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parse_listing_html(
            listing_html(),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=1,
        )


def test_rey_reconciles_detail_identity_and_application_url() -> None:
    kwargs = {
        "page_url": job_url(SERVICE_SLUG),
        "expected_url": job_url(SERVICE_SLUG),
        "expected_title": "Software Engineer Service (m/f/d)",
        "expected_location": "Sirnach or Arlesheim",
        "expected_workload": "100%",
        "expected_start": "by arrangement",
        "expected_job_id": SERVICE_SLUG,
    }
    wrong_title = detail_html(
        slug=SERVICE_SLUG,
        title="Chief Executive Officer",
        location="Sirnach or Arlesheim",
        workload="100 %",
    )
    unsafe_apply = detail_html(
        slug=SERVICE_SLUG,
        title="Software Engineer Service (m/f/d)",
        location="Sirnach or Arlesheim",
        workload="100 %",
        apply_url="https://attacker.example/apply",
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(wrong_title, **kwargs)
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(unsafe_apply, **kwargs)


def test_rey_wraps_catalog_request_failures() -> None:
    parser = ReyTechnologyJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_rey_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["rey_technology"]
    assert isinstance(parser, ReyTechnologyJobsParser)
    assert parser.base_url == settings.rey_technology_jobs_base_url
    assert parser.max_jobs == settings.rey_technology_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Rey Technology", "filters": {}},
            "sources": ["rey_technology", "rey_technology"],
        }
    )
    assert request.sources == ["rey_technology"]


def test_rey_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": SERVICE_SLUG,
            "title": "Software Engineer Service (m/f/d)",
            "location": "Sirnach or Arlesheim, Switzerland",
            "workload": "100%",
            "url": job_url(SERVICE_SLUG),
            "apply_url": REY_APPLICATION_URL,
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"rey_technology-{SERVICE_SLUG}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Rey Technology import"
    assert stored["id"] == f"rey_technology-{SERVICE_SLUG}"
