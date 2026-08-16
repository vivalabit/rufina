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
from app.services.parsers.companies.jnj_switzerland import (
    JNJ_RESULTS_PER_PAGE,
    JnjSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, multiple: bool = False) -> dict[str, str]:
    job_id = f"r-{93_100 + index:06d}"
    return {
        "job_id": job_id,
        "title": f"J&J role {index}",
        "location": "Hyderabad / Allschwil / Raritan" if multiple else "Schaffhausen",
        "category": "Technology Product & Platform Management",
        "url": (
            f"https://www.careers.jnj.com/en/jobs/{job_id}/"
            f"jnj-role-{index}/"
        ),
    }


def listing_html(
    records: list[dict[str, str]],
    *,
    total: int,
    page: int,
    selected_country: str = "Switzerland",
    current_page: int | None = None,
) -> str:
    current_page = page if current_page is None else current_page
    start = ((current_page - 1) * JNJ_RESULTS_PER_PAGE) + 1
    end = min(current_page * JNJ_RESULTS_PER_PAGE, total)
    page_suffix = f" - Page {page}" if page > 1 else ""
    canonical_suffix = f"?page={page}" if page > 1 else ""
    cards = "".join(
        f"""
        <div class="PagePromo-contentWrap">
          <h3 class="PagePromo-title">
            <a class="stretched-link Link js-view-job"
              href="{urlsplit(record['url']).path}">{record['title']}</a>
          </h3>
          <div class="PagePromo-category">{record['category']}</div>
          <address class="PagePromo-location">{record['location']}</address>
          <div class="job-actions js-job" data-id="{record['job_id']}"
            data-jobtitle="{record['title']}"></div>
        </div>
        """
        for record in records
    )
    return f"""
    <html><head>
      <title>Explore current job openings | Johnson &amp; Johnson Careers{page_suffix}</title>
      <link rel="canonical" href="https://www.careers.jnj.com/en/jobs/{canonical_suffix}" />
    </head><body><main>
      <form id="job-filter">
        <select name="country"><option value="{selected_country}" selected>
          {selected_country}</option></select>
      </form>
      <h2>Displaying {start} to {end} of {total} matching jobs</h2>
      {cards}
    </main></body></html>
    """


def empty_listing_html() -> str:
    return """
    <html><head>
      <title>Explore current job openings | Johnson &amp; Johnson Careers</title>
      <link rel="canonical" href="https://www.careers.jnj.com/en/jobs/" />
    </head><body><main>
      <select name="country"><option value="Switzerland" selected>Switzerland</option></select>
      <p class="lead">Sorry, there are no results that match your criteria.</p>
    </main></body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    swiss: bool = True,
    include_foreign: bool = False,
) -> str:
    locations: list[dict[str, object]] = []
    if swiss:
        locations.append(
            {
                "@type": "Place",
                "name": "Allschwil" if include_foreign else "Schaffhausen",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Allschwil" if include_foreign else "Schaffhausen",
                    "addressRegion": "Basel-Country" if include_foreign else "Schaffhausen",
                    "addressCountry": "Switzerland",
                },
            }
        )
    if include_foreign or not swiss:
        locations.append(
            {
                "@type": "Place",
                "name": "Hyderabad",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Hyderabad",
                    "addressCountry": "India",
                },
            }
        )
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": record["title"],
        "description": (
            "<p>Shape the future of health.</p>"
            "<ul><li>Build trusted systems</li><li>Support patients</li></ul>"
        ),
        "identifier": record["job_id"].upper(),
        "url": record["url"],
        "datePosted": "2026-08-14",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Johnson & Johnson Services, Inc.",
        },
        "jobLocation": locations,
    }
    apply_url = (
        "https://jj.wd5.myworkdayjobs.com/en-US/JJ/job/Schaffhausen-Switzerland/"
        f"J-J-role_{record['job_id'].upper()}/apply"
    )
    return f"""
    <html><head>
      <link rel="canonical" href="{record['url']}" />
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head><body><main>
      <a class="js-apply-external" href="{apply_url}">Apply now</a>
      <a class="js-apply-external" href="{apply_url}">Apply now</a>
    </main></body></html>
    """


def parser_with(fetch_page: object, **kwargs: object) -> JnjSwitzerlandJobsParser:
    return JnjSwitzerlandJobsParser(fetch_page=fetch_page, **kwargs)  # type: ignore[arg-type]


def test_jnj_collects_every_country_page_and_enriches_jobs() -> None:
    records = [listing_record(index, multiple=index == 0) for index in range(21)]
    listing_pages: list[int] = []

    def fetch_page(url: str) -> Selector:
        parts = urlsplit(url)
        if parts.path == "/en/jobs/":
            page = int(parse_qs(parts.query).get("page", ["1"])[0])
            listing_pages.append(page)
            assert parse_qs(parts.query)["country"] == ["Switzerland"]
            start = (page - 1) * JNJ_RESULTS_PER_PAGE
            return Selector(
                listing_html(
                    records[start : start + JNJ_RESULTS_PER_PAGE],
                    total=len(records),
                    page=page,
                )
            )
        record = next(item for item in records if parts.path == urlsplit(item["url"]).path)
        return Selector(
            detail_html(record, include_foreign=record is records[0])
        )

    result = parser_with(fetch_page).search(LinkedInSearchRequest())

    assert sorted(listing_pages) == [1, 2]
    assert len(result.jobs) == 21
    assert result.message == (
        "Scanned 21 verified Johnson & Johnson Switzerland vacancies from 21 "
        "country records across 2 page requests in 1 catalog pass(es)"
    )
    first = result.jobs[0]
    assert first.source == "jnj_switzerland"
    assert first.company == "Johnson & Johnson"
    assert first.location == "Allschwil, Basel-Country, Switzerland"
    assert "India" not in first.location
    assert first.posted_at == "2026-08-14"
    assert first.employment_type == "Full Time"
    assert first.apply_url and first.apply_url.endswith("/apply")
    assert first.description == (
        "Shape the future of health.\n- Build trusted systems\n- Support patients"
    )
    assert first.raw["listing_page"] == 1
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 21


def test_jnj_preserves_country_scoped_listing_when_detail_fails() -> None:
    record = listing_record(1, multiple=True)

    def fetch_page(url: str) -> Selector:
        if urlsplit(url).path == "/en/jobs/":
            return Selector(listing_html([record], total=1, page=1))
        return Selector("<html><body>Temporary detail error</body></html>")

    job = parser_with(fetch_page).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Hyderabad / Allschwil / Raritan, Switzerland"
    assert job.apply_url == record["url"]
    assert "one JobPosting" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page_html", "match"),
    [
        (
            listing_html(
                [listing_record(1)],
                total=1,
                page=1,
                selected_country="Germany",
            ),
            "did not preserve",
        ),
        (
            listing_html(
                [listing_record(1)],
                total=1,
                page=1,
                current_page=2,
            ),
            "pagination metadata",
        ),
        (
            listing_html([], total=1, page=1),
            "returned 0 of 1",
        ),
    ],
)
def test_jnj_rejects_malformed_or_unscoped_catalogs(
    page_html: str,
    match: str,
) -> None:
    def fetch_page(url: str) -> Selector:
        return Selector(page_html)

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser_with(fetch_page).search(LinkedInSearchRequest())


def test_jnj_rejects_foreign_detail_but_keeps_verified_listing() -> None:
    record = listing_record(1)

    def fetch_page(url: str) -> Selector:
        if urlsplit(url).path == "/en/jobs/":
            return Selector(listing_html([record], total=1, page=1))
        return Selector(detail_html(record, swiss=False))

    job = parser_with(fetch_page).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Schaffhausen, Switzerland"
    assert "non-Swiss JobPosting" in str(job.raw["detail_error"])


def test_jnj_accepts_verified_empty_catalog() -> None:
    def fetch_page(url: str) -> Selector:
        return Selector(empty_listing_html())

    result = parser_with(fetch_page).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith(
        "Scanned 0 verified Johnson & Johnson Switzerland vacancies"
    )


def test_jnj_rejects_catalog_above_page_limit() -> None:
    records = [listing_record(index) for index in range(JNJ_RESULTS_PER_PAGE)]

    def fetch_page(url: str) -> Selector:
        return Selector(listing_html(records, total=41, page=1))

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        parser_with(fetch_page, max_pages=2).search(LinkedInSearchRequest())


def test_jnj_rejects_base_url_without_switzerland_filter() -> None:
    parser = JnjSwitzerlandJobsParser(
        base_url="https://www.careers.jnj.com/en/jobs/?origin=global",
        fetch_page=lambda url: Selector("<html></html>"),
    )

    with pytest.raises(DirectCompanyRequestError, match="Switzerland filter"):
        parser.search(LinkedInSearchRequest())


def test_jnj_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["jnj_switzerland"]

    assert isinstance(parser, JnjSwitzerlandJobsParser)
    assert parser.base_url == settings.jnj_switzerland_jobs_base_url
    assert parser.max_pages == settings.jnj_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.jnj_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Johnson & Johnson Switzerland", "filters": {}},
            "sources": ["jnj_switzerland", "jnj_switzerland"],
        }
    )
    assert request.sources == ["jnj_switzerland"]

    record = listing_record(1)
    record["detail"] = {
        "title": record["title"],
        "location": "Schaffhausen, Schaffhausen, Switzerland",
        "url": record["url"],
        "apply_url": record["url"],
        "description": "<p>Swiss J&J role</p>",
    }
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="jnj_switzerland-r-093101",
        added_at=datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Johnson & Johnson Switzerland import"
    assert stored["company"] == "Johnson & Johnson"
