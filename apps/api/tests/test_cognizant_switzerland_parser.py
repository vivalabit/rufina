from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.cognizant_switzerland import (
    CognizantSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def json(self) -> object:
        raise AssertionError("HTML response is not JSON")

    def css(self, selector: str, *args: object, **kwargs: object) -> object:
        return self.selector.css(selector, *args, **kwargs)


def listing_card(job_id: int, *, title: str) -> str:
    return f"""
    <div class="card card-job" data-id="{job_id}">
      <div class="card-body">
        <h2 class="card-title">
          <a href="/global-en/jobs/{job_id}/cloud-engineer-{job_id}/">
            {title}
          </a>
        </h2>
        <ul class="list-inline job-meta">
          <li class="list-inline-item">
            Zurich, NETCENTRIC AG, Zurich, Switzerland
          </li>
          <li class="list-inline-item">Digital</li>
        </ul>
      </div>
    </div>
    """


def listing_html(
    cards: list[str],
    *,
    start: int,
    end: int,
    total: int,
) -> str:
    return f"""
    <html><body><main id="results">
      <p class="job-count">
        Displaying <strong>{start}</strong> to <strong>{end}</strong>
        of <strong>{total}</strong> matching jobs
      </p>
      {"".join(cards)}
    </main></body></html>
    """


def detail_html(job_id: int, *, title: str) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<div><h3>What you'll do</h3>"
            "<ul><li>Build cloud platforms</li><li>Support clients</li></ul></div>"
        ),
        "identifier": str(job_id),
        "mainEntityOfPage": (
            f"https://careers.cognizant.test/global-en/jobs/{job_id}/cloud-engineer-{job_id}/"
        ),
        "url": (f"https://careers.cognizant.test/global-en/jobs/{job_id}/cloud-engineer-{job_id}/"),
        "datePosted": "2026-08-08",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Cognizant",
        },
        "industry": "Digital",
        "jobLocation": {
            "@type": "Place",
            "name": "Zurich, NETCENTRIC AG",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "Switzerland",
                "addressLocality": "Zurich",
                "addressRegion": "Zurich",
            },
        },
    }
    return f"""
    <html><body><main>
      <h1>{title}</h1>
      <script type="application/ld+json">{json.dumps(schema)}</script>
      <a href="https://cognizant.taleo.test/careersection/Lateral/jobapply.ftl?job={job_id}&lang=en">
        Apply now
      </a>
    </main></body></html>
    """


def test_cognizant_scans_every_page_and_enriches_details() -> None:
    listing_calls: list[int] = []

    def fetch_page(url: str) -> HtmlResponse:
        parts = urlsplit(url)
        if "/jobs/" == parts.path.rsplit("global-en", maxsplit=1)[-1]:
            page = int(parse_qs(parts.query).get("page", ["1"])[0])
            listing_calls.append(page)
            assert parse_qs(parts.query, keep_blank_values=True)["ccode"] == ["CH"]
            if page == 1:
                return HtmlResponse(
                    listing_html(
                        [
                            listing_card(47_000 + index, title=f"Cloud Engineer {index}")
                            for index in range(10)
                        ],
                        start=1,
                        end=10,
                        total=11,
                    )
                )
            return HtmlResponse(
                listing_html(
                    [listing_card(47_010, title="Cloud Engineer 10")],
                    start=11,
                    end=11,
                    total=11,
                )
            )

        job_id = int(parts.path.split("/jobs/", maxsplit=1)[1].split("/", maxsplit=1)[0])
        return HtmlResponse(detail_html(job_id, title=f"Cloud Engineer {job_id - 47_000}"))

    parser = CognizantSwitzerlandJobsParser(
        base_url=(
            "https://careers.cognizant.test/global-en/jobs/?keyword=&location=Switzerland&ccode=CH"
        ),
        detail_workers=4,
        fetch_page=fetch_page,
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_calls == [1, 2]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 11 Cognizant Switzerland vacancies from 11 catalog records across 2 page requests"
    )
    assert len(result.jobs) == 11
    first = result.jobs[0]
    assert first.source == "cognizant_switzerland"
    assert first.title == "Cloud Engineer 0"
    assert first.company == "Cognizant"
    assert first.location == "Zurich, NETCENTRIC AG, Zurich, Switzerland"
    assert first.url == (
        "https://careers.cognizant.test/global-en/jobs/47000/cloud-engineer-47000/"
    )
    assert first.apply_url == (
        "https://cognizant.taleo.test/careersection/Lateral/jobapply.ftl?job=47000&lang=en"
    )
    assert first.posted_at == "2026-08-08"
    assert first.employment_type == "Full-time"
    assert first.description == ("What you'll do\n- Build cloud platforms\n- Support clients")
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 11


def test_cognizant_retries_shifted_catalog_pages() -> None:
    listing_calls: list[int] = []

    def fetch_page(url: str) -> HtmlResponse:
        parts = urlsplit(url)
        if "/jobs/" == parts.path.rsplit("global-en", maxsplit=1)[-1]:
            page = int(parse_qs(parts.query).get("page", ["1"])[0])
            listing_calls.append(page)
            if page == 1:
                cards = [
                    listing_card(47_000 + index, title=f"Cloud Engineer {index}")
                    for index in range(10)
                ]
                return HtmlResponse(listing_html(cards, start=1, end=10, total=11))
            job_id = 47_009 if listing_calls.count(2) == 1 else 47_010
            return HtmlResponse(
                listing_html(
                    [listing_card(job_id, title=f"Cloud Engineer {job_id - 47_000}")],
                    start=11,
                    end=11,
                    total=11,
                )
            )
        job_id = int(parts.path.split("/jobs/", maxsplit=1)[1].split("/", maxsplit=1)[0])
        return HtmlResponse(detail_html(job_id, title=f"Cloud Engineer {job_id - 47_000}"))

    result = CognizantSwitzerlandJobsParser(
        max_catalog_passes=2,
        fetch_page=fetch_page,
    ).search(LinkedInSearchRequest())

    assert listing_calls == [1, 2, 1, 2]
    assert len(result.jobs) == 11
    assert result.message.endswith("across 4 page requests")


def test_cognizant_preserves_safe_listing_when_detail_fails() -> None:
    def fetch_page(url: str) -> HtmlResponse:
        if urlsplit(url).path.endswith("/jobs/"):
            return HtmlResponse(
                listing_html(
                    [listing_card(47_495, title="Onsite Support Services Engineer")],
                    start=1,
                    end=1,
                    total=1,
                )
            )
        raise RuntimeError("detail temporarily unavailable")

    job = (
        CognizantSwitzerlandJobsParser(fetch_page=fetch_page)
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Onsite Support Services Engineer"
    assert job.company == "Cognizant Technology Solutions AG"
    assert job.location == "Zurich, NETCENTRIC AG, Zurich, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "temporarily unavailable" in str(job.raw["detail_error"])


def test_cognizant_rejects_malformed_or_non_swiss_listing() -> None:
    malformed = CognizantSwitzerlandJobsParser(
        fetch_page=lambda _: HtmlResponse("<html><body>Jobs</body></html>")
    )
    foreign_html = listing_html(
        [listing_card(47_495, title="Engineer").replace("Switzerland", "Germany")],
        start=1,
        end=1,
        total=1,
    )
    foreign = CognizantSwitzerlandJobsParser(fetch_page=lambda _: HtmlResponse(foreign_html))

    with pytest.raises(DirectCompanyRequestError, match="result range"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        foreign.search(LinkedInSearchRequest())


def test_cognizant_enforces_catalog_page_limit() -> None:
    parser = CognizantSwitzerlandJobsParser(
        max_pages=1,
        fetch_page=lambda _: HtmlResponse(
            listing_html(
                [
                    listing_card(47_000 + index, title=f"Cloud Engineer {index}")
                    for index in range(10)
                ],
                start=1,
                end=10,
                total=11,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_cognizant_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["cognizant_switzerland"]
    assert isinstance(parser, CognizantSwitzerlandJobsParser)
    assert parser.base_url == settings.cognizant_switzerland_jobs_base_url
    assert parser.max_pages == settings.cognizant_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.cognizant_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.cognizant_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Cognizant Switzerland", "filters": {}},
            "sources": ["cognizant_switzerland", "cognizant_switzerland"],
        }
    )
    assert request.sources == ["cognizant_switzerland"]


def test_cognizant_jobs_render_as_direct_company_imports() -> None:
    parser = CognizantSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "47495",
            "title": "Onsite Support Services Engineer",
            "location": "Zurich, Switzerland",
            "url": (
                "https://careers.cognizant.com/global-en/jobs/47495/"
                "onsite-support-services-engineer/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="cognizant_switzerland-47495",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Cognizant Technology Solutions AG import"
    assert stored["id"] == "cognizant_switzerland-47495"
