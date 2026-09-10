from __future__ import annotations

import html
from datetime import UTC, datetime

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.lonza_switzerland import (
    LonzaSwitzerlandJobsParser,
    canonical_apply_url,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.lonza.test/careers/job-search"
LISTING_ID = "5554d949-7794-4dfb-a682-f427b424686f"
SWISS_LOCATIONS = (
    "Switzerland, Basel",
    "Switzerland, Stein",
    "Switzerland, Visp",
)


def search_form(*, page: int = 1, checked: bool = False) -> str:
    location_inputs = [
        '<input name="job_location_facet_sm" value="Germany, Cologne">'
    ]
    location_inputs.extend(
        (
            '<input name="job_location_facet_sm" '
            f'value="{location}"{" checked" if checked else ""}>'
        )
        for location in SWISS_LOCATIONS
    )
    return f"""
      <form id="link-form" method="POST">
        <input type="hidden" name="q" value="">
        <input type="hidden" name="pg" value="{page}">
        <input type="hidden" name="lid" value="{LISTING_ID}">
      </form>
      {''.join(location_inputs)}
    """


def listing_card(
    job_id: str,
    title: str,
    *,
    location: str = "Switzerland, Visp",
) -> str:
    return f"""
      <a class="search-result cta -result" href="/jobs/{job_id}">
        <div class="search-result-main">
          <div class="search-result-title">{html.escape(title)}</div>
          <div class="search-result-content">{html.escape(location)}</div>
        </div>
      </a>
    """


def listing_page(
    cards: list[str],
    *,
    page: int,
    start: int,
    end: int,
    total: int,
) -> Selector:
    return Selector(
        f"""
        <html><body>
          {search_form(page=page, checked=True)}
          <div class="page-count">Showing {start}‐{end} of {total}</div>
          <div class="search-results">{''.join(cards)}</div>
        </body></html>
        """
    )


def discovery_page() -> Selector:
    return Selector(
        f"""
        <html><head>
          <link rel="canonical" href="https://www.lonza.com/careers/job-search">
        </head><body>{search_form()}</body></html>
        """
    )


def detail_page(
    job_id: str,
    title: str,
    *,
    location: str = "Switzerland, Visp",
) -> Selector:
    description = """
      <p>Help manufacture medicines that improve patients' lives around the world.</p>
      <p><b>Your responsibilities:</b></p>
      <ul><li>Lead cross-functional projects.</li><li>Maintain GMP standards.</li></ul>
      <p>Every day, Lonza teams work together to deliver meaningful therapies.</p>
    """
    return Selector(
        f"""
        <html><head>
          <link rel="canonical" href="https://www.lonza.com/jobs/{job_id}">
        </head><body><main>
          <section class="cmp-job-posting">
            <section class="detail-page-hero"><div class="h1">{html.escape(title)}</div></section>
            <div class="job-posting"><div class="row"><div class="col-md-8">
              <div class="job-posting-location"><span>{html.escape(location)}</span></div>
              {description}
              <div class="h6">Reference: {job_id}</div>
              <a class="btn apply" href="https://lonza.talent-community.com/projects/ext/{job_id}/apply?utm_source=careersite&amp;utm_medium=referral">Apply</a>
            </div></div></div>
          </section>
        </main></body></html>
        """
    )


def test_lonza_scans_complete_swiss_catalog_and_enriches_jobs() -> None:
    records = {
        "R78588": (
            "Schichtteamleiter 80-100% (m/w/d)",
            "Switzerland, Visp",
        ),
        "R78589": (
            "Senior Business Development Manager",
            "Switzerland, Basel; Switzerland, Stein; United Kingdom, Slough",
        ),
    }
    get_requests: list[str] = []
    post_requests: list[list[tuple[str, str]]] = []

    def fetch_get(url: str) -> Selector:
        get_requests.append(url)
        if url == BASE_URL:
            return discovery_page()
        job_id = url.rsplit("/", 1)[-1]
        title, location = records[job_id]
        return detail_page(job_id, title, location=location)

    def fetch_post(_url: str, data: list[tuple[str, str]]) -> Selector:
        post_requests.append(data)
        values = dict(data)
        page = int(values["pg"])
        job_id = "R78588" if page == 1 else "R78589"
        title, location = records[job_id]
        return listing_page(
            [listing_card(job_id, title, location=location)],
            page=page,
            start=page,
            end=page,
            total=2,
        )

    result = LonzaSwitzerlandJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        fetch_get=fetch_get,
        fetch_post=fetch_post,
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 Lonza Switzerland vacancies from 2 catalog records across "
        "2 filtered page requests"
    )
    assert get_requests == [
        BASE_URL,
        "https://www.lonza.com/jobs/R78588",
        "https://www.lonza.com/jobs/R78589",
    ]
    assert len(post_requests) == 2
    assert [dict(data)["pg"] for data in post_requests] == ["1", "2"]
    assert [
        value
        for key, value in post_requests[0]
        if key == "job_location_facet_sm"
    ] == list(SWISS_LOCATIONS)

    first = result.jobs[0]
    assert first.source == "lonza_switzerland"
    assert first.title == "Schichtteamleiter 80-100% (m/w/d)"
    assert first.company == "Lonza"
    assert first.location == "Switzerland, Visp"
    assert first.url == "https://www.lonza.com/jobs/R78588"
    assert first.apply_url == (
        "https://lonza.talent-community.com/projects/ext/R78588/apply?"
        "utm_medium=referral&utm_source=careersite"
    )
    assert first.employment_type == "80-100%"
    assert first.description == (
        "Help manufacture medicines that improve patients' lives around the world.\n"
        "Your responsibilities:\n"
        "- Lead cross-functional projects.\n"
        "- Maintain GMP standards.\n"
        "\n"
        "Every day, Lonza teams work together to deliver meaningful therapies."
    )
    assert first.raw["detail"]["id"] == "R78588"
    assert first.raw["total_available"] == 2
    assert result.jobs[1].seniority == "Senior"


def test_lonza_preserves_listing_when_detail_fails() -> None:
    title = "Automation Engineer"

    def fetch_get(url: str) -> Selector:
        if url == BASE_URL:
            return discovery_page()
        raise RuntimeError("detail unavailable")

    job = (
        LonzaSwitzerlandJobsParser(
            base_url=BASE_URL,
            fetch_get=fetch_get,
            fetch_post=lambda _url, _data: listing_page(
                [listing_card("R78001", title)],
                page=1,
                start=1,
                end=1,
                total=1,
            ),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == title
    assert job.company == "Lonza"
    assert job.location == "Switzerland, Visp"
    assert job.apply_url == "https://www.lonza.com/jobs/R78001"
    assert job.description is None
    assert job.raw["detail_error"] == "detail unavailable"


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (Selector("<html></html>"), "missing its official search form"),
        (
            Selector(
                '<form id="link-form" method="POST">'
                '<input name="lid" value="invalid"></form>'
            ),
            "invalid listing ID",
        ),
    ],
)
def test_lonza_rejects_invalid_discovery_pages(
    page: Selector,
    message: str,
) -> None:
    parser = LonzaSwitzerlandJobsParser(
        base_url=BASE_URL,
        fetch_get=lambda _url: page,
        fetch_post=lambda _url, _data: page,
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("cards", "message"),
    [
        ([], "inconsistent result metadata"),
        (
            [listing_card("R78001", "Engineer", location="Germany, Cologne")],
            "incomplete or non-Swiss",
        ),
        (
            [
                listing_card("R78001", "Engineer"),
                listing_card("R78001", "Engineer"),
            ],
            "duplicate vacancy IDs",
        ),
    ],
)
def test_lonza_rejects_invalid_filtered_catalogs(
    cards: list[str],
    message: str,
) -> None:
    parser = LonzaSwitzerlandJobsParser(
        base_url=BASE_URL,
        fetch_get=lambda _url: discovery_page(),
        fetch_post=lambda _url, _data: listing_page(
            cards,
            page=1,
            start=1,
            end=max(1, len(cards)),
            total=max(1, len(cards)),
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_lonza_enforces_page_limit_and_wraps_request_errors() -> None:
    too_large = LonzaSwitzerlandJobsParser(
        base_url=BASE_URL,
        max_pages=1,
        fetch_get=lambda _url: discovery_page(),
        fetch_post=lambda _url, _data: listing_page(
            [listing_card("R78001", "Engineer")],
            page=1,
            start=1,
            end=1,
            total=2,
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = LonzaSwitzerlandJobsParser(
        base_url=BASE_URL,
        fetch_get=lambda _url: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_lonza_validates_reference_bound_application_url() -> None:
    url = (
        "https://lonza.talent-community.com/projects/ext/R78588/apply?"
        "utm_source=careersite&utm_medium=referral"
    )

    assert canonical_apply_url(url, expected_job_id="R78588") == (
        "https://lonza.talent-community.com/projects/ext/R78588/apply?"
        "utm_medium=referral&utm_source=careersite"
    )
    assert canonical_apply_url(url, expected_job_id="R11111") is None


def test_lonza_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["lonza_switzerland"]
    assert isinstance(parser, LonzaSwitzerlandJobsParser)
    assert parser.base_url == settings.lonza_switzerland_jobs_base_url
    assert parser.max_pages == settings.lonza_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.lonza_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == settings.lonza_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Lonza Switzerland", "filters": {}},
            "sources": ["lonza_switzerland", "lonza_switzerland"],
        }
    )
    assert request.sources == ["lonza_switzerland"]


def test_lonza_jobs_render_as_direct_company_imports() -> None:
    job = LonzaSwitzerlandJobsParser().normalize_job(
        {
            "id": "R78588",
            "title": "Schichtteamleiter 80-100% (m/w/d)",
            "company": "Lonza",
            "location": "Switzerland, Visp",
            "url": "https://www.lonza.com/jobs/R78588",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="lonza_switzerland-R78588",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Lonza Switzerland import"
    assert stored["company"] == "Lonza"
    assert stored["id"] == "lonza_switzerland-R78588"


def test_lonza_accepts_workday_application_with_matching_reference() -> None:
    from app.services.parsers.companies.lonza_switzerland import canonical_apply_url
    url = "https://lonza.wd3.myworkdayjobs.com/Lonza_Careers/job/CH---Basel/Senior-Vice-President--Corporate-Finance_R79385/apply"
    assert canonical_apply_url(url, expected_job_id="R79385") == url
    assert canonical_apply_url(url, expected_job_id="R99999") is None
    assert canonical_apply_url(url.replace("lonza.wd3", "other.wd3"), expected_job_id="R79385") is None


def test_lonza_reads_wrapped_description_blocks_once() -> None:
    from app.services.parsers.companies.lonza_switzerland import parse_detail_page
    page = detail_page("R79385", "Engineer").get()
    page = page.replace("<p>Help", "<div><p>Help").replace(
        "meaningful therapies.</p>", "meaningful therapies.</p></div>",
    )
    detail = parse_detail_page(
        Selector(page), page_url="https://www.lonza.com/jobs/R79385",
        expected_job_id="R79385", expected_title="Engineer",
    )
    assert detail["description"].count("Lead cross-functional projects.") == 1
    assert "Reference:" not in detail["description"]
