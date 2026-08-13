from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.comerge import ComergeJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.comerge.test/en/career#"


def page_head(canonical_url: str, *, language: str = "en-CH") -> str:
    return f"""
    <head>
      <meta http-equiv="content-language" content="{language}">
      <link rel="canonical" href="{canonical_url}">
    </head>
    """


def footer(*, company: str = "Comerge AG", city: str = "8045 Zurich") -> str:
    return f"""
    <div class="footer">
      <div class="column-29">
        <h3><strong class="white">{company}</strong></h3>
        <p class="paragraph inverted">
          Bubenbergstrasse 1<br>{city}<br>Tel: +41 44 552 52 62
        </p>
      </div>
    </div>
    """


def listing_card(
    job_id: str,
    *,
    title: str,
    workload: str = "(m/f/d) 80%-100%",
    summary: str = "with a degree in Computer Science.",
    href: str | None = None,
) -> str:
    return f"""
    <div role="listitem" class="collection-item-4 w-dyn-item">
      <a href="{href or f"/en/career/{job_id}"}"
         class="link-block-5 w-inline-block">
        <h1 class="heading-6 english">{title}</h1>
      </a>
      <div class="bold-text english">{workload}</div>
      <div class="text-block english">{summary}</div>
    </div>
    """


def listing_html(cards: list[str], *, company: str = "Comerge AG") -> str:
    return f"""
    <html>
      {page_head("https://www.comerge.test/en/career")}
      <body>
        <div class="collection-list-wrapper-3 w-dyn-list">
          <div role="list" class="w-dyn-items">{"".join(cards)}</div>
        </div>
        {footer(company=company)}
      </body>
    </html>
    """


def detail_html(
    job_id: str,
    *,
    title: str,
    workload: str = "(m/f/d) 80%-100%",
    apply_title: str | None = None,
    canonical_url: str | None = None,
    company: str = "Comerge AG",
) -> str:
    subject = quote(f"Application: {apply_title or title}", safe="")
    canonical = canonical_url or f"https://www.comerge.test/en/career/{job_id}"
    return f"""
    <html>
      {page_head(canonical)}
      <body>
        <div class="container-with-background english w-container">
          <div class="div-block-9">
            <strong class="bold-text-6">
              We are Comerge, a team of software developers and designers.
            </strong>
          </div>
          <h1 class="heading-huge red">{title}</h1>
          <h1 class="heading-huge red regular">{workload}</h1>
          <div class="rich-text-block-3 w-richtext">
            <p>Build sustainable software solutions.</p>
            <p><strong>What you'll do</strong></p>
            <ul>
              <li>Develop reliable applications.</li>
              <li>Collaborate with clients and the team.</li>
            </ul>
            <div class="job-application">
              <div class="job-application-link">
                <a class="bold-text"
                   href="mailto:jobs@comerge.net?subject={subject}">Apply now</a>
              </div>
              <p class="job-application-address">
                Comerge AG<br>HR Department<br>
                <a href="mailto:jobs@comerge.net">jobs@comerge.net</a><br>
                <a href="tel:+41445525262">+41 44 552 52 62</a>
              </p>
            </div>
          </div>
        </div>
        {footer(company=company)}
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "machine-learning-computer-vision-engineer",
            title="Machine Learning / Computer Vision Engineer",
        ),
        listing_card(
            "software-engineer",
            title="Senior Software Engineer",
            summary="with several years of professional experience.",
        ),
    ]


def test_comerge_collects_full_catalog_and_enriches_every_vacancy() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/en/career":
            return httpx.Response(
                200,
                text=listing_html(catalog_fixture()),
                request=request,
            )
        job_id = request.url.path.removeprefix("/en/career/")
        title = (
            "Machine Learning / Computer Vision Engineer"
            if job_id == "machine-learning-computer-vision-engineer"
            else "Senior Software Engineer"
        )
        return httpx.Response(
            200,
            text=detail_html(job_id, title=title),
            request=request,
        )

    result = ComergeJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/en/career",
        "/en/career/machine-learning-computer-vision-engineer",
        "/en/career/software-engineer",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Comerge Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "comerge"
    assert job.title == "Machine Learning / Computer Vision Engineer"
    assert job.company == "Comerge AG"
    assert job.location == "Zurich, Switzerland"
    assert job.url == (
        "https://www.comerge.test/en/career/machine-learning-computer-vision-engineer"
    )
    assert job.apply_url == (
        "mailto:jobs@comerge.net?subject=Application%3A%20Machine%20Learning%20%2F%20"
        "Computer%20Vision%20Engineer"
    )
    assert job.posted_at is None
    assert job.employment_type == "80–100%"
    assert job.description == (
        "Build sustainable software solutions.\n\n"
        "What you'll do\n\n"
        "- Develop reliable applications.\n"
        "- Collaborate with clients and the team."
    )
    assert job.raw["detail"]["id"] == "machine-learning-computer-vision-engineer"


def test_comerge_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career":
            return httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "software-engineer",
                            title="Senior Software Engineer",
                            summary="Senior full-stack profile.",
                        )
                    ]
                ),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        ComergeJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Software Engineer"
    assert job.location == "Zurich, Switzerland"
    assert job.apply_url == job.url
    assert job.description == "Senior full-stack profile."
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_comerge_rejects_duplicate_unsafe_or_invalid_catalog_records() -> None:
    card = listing_card("software-engineer", title="Senior Software Engineer")

    def parser_for(cards: list[str]) -> ComergeJobsParser:
        return ComergeJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(cards),
                    request=request,
                )
            ),
        )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([card, card]).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser_for(
            [
                listing_card(
                    "software-engineer",
                    title="Senior Software Engineer",
                    href="https://attacker.example/en/career/software-engineer",
                )
            ]
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="invalid workload"):
        parser_for(
            [
                listing_card(
                    "software-engineer",
                    title="Senior Software Engineer",
                    workload="Full time",
                )
            ]
        ).search(LinkedInSearchRequest())


def test_comerge_rejects_missing_or_non_swiss_catalog_identity() -> None:
    missing = ComergeJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<html><body>Career</body></html>",
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        missing.search(LinkedInSearchRequest())

    non_swiss = ComergeJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), company="Other AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="Swiss company identity"):
        non_swiss.search(LinkedInSearchRequest())


def test_comerge_rejects_mismatched_detail_or_application_contract() -> None:
    detail_url = "https://www.comerge.test/en/career/software-engineer"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "software-engineer",
                title="Senior Software Engineer",
                apply_title="Different Role",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="software-engineer",
            expected_title="Senior Software Engineer",
            expected_workload="80–100%",
        )

    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html("software-engineer", title="Senior Software Engineer"),
            page_url=detail_url,
            expected_url=(
                "https://www.comerge.test/en/career/machine-learning-computer-vision-engineer"
            ),
            expected_job_id="machine-learning-computer-vision-engineer",
            expected_title="Machine Learning / Computer Vision Engineer",
            expected_workload="80–100%",
        )


def test_comerge_wraps_listing_request_failures() -> None:
    parser = ComergeJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_comerge_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["comerge"]
    assert isinstance(parser, ComergeJobsParser)
    assert parser.base_url == settings.comerge_jobs_base_url
    assert parser.detail_workers == settings.comerge_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Comerge", "filters": {}},
            "sources": ["comerge", "comerge"],
        }
    )
    assert request.sources == ["comerge"]


def test_comerge_jobs_render_as_direct_company_imports() -> None:
    job = ComergeJobsParser().normalize_job(
        {
            "id": "software-engineer",
            "title": "Senior Software Engineer",
            "workload": "80–100%",
            "location": "Zurich, Switzerland",
            "url": "https://www.comerge.net/en/career/software-engineer",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="comerge-software-engineer",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Comerge import"
    assert stored["id"] == "comerge-software-engineer"
