from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.six_group import SixGroupJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://jobs.six-group.test/search/"


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Zurich, CH",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="/job/Zurich-Application-Engineer/{job_id}/">
              Application Engineer {job_id} (80 - 100%)
            </a>
          </td>
          <td class="colLocation">
            <span class="jobLocation">{location}</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <span class="paginationLabel">Results {start} – {end} of {total}</span>
      <table id="searchresults"
             aria-label="Results {start} to {end} of {total}">
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def detail_html(
    job_id: int,
    *,
    title: str | None = None,
    company: str = "SIX",
    location: str = "Zurich, CH",
    additional_locations: tuple[str, ...] = (),
) -> str:
    job_title = title or f"Application Engineer {job_id} (80 - 100%)"
    location_markup = "".join(
        f'<meta itemprop="streetAddress" content="{value}">'
        for value in (location, *additional_locations)
    )
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Thu Aug 13 02:01:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="{company}">
        <span itemprop="jobLocation"><span itemprop="address">
          {location_markup}
        </span></span>
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <h1>{job_title}</h1>
            <p>SIX drives the transformation of financial markets.</p>
            <div><h2>What You Will Do</h2>
              <ul><li>Develop reliable financial applications.</li></ul>
            </div>
            <div><h2>What You Bring</h2>
              <ul><li>Experience with distributed systems.</li></ul>
            </div>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=en_US">Apply now</a>
      </div>
    </body></html>
    """


def test_six_group_scans_full_swiss_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["optionsFacetsDD_country"] == "CH"
            assert request.url.params["locale"] == "en_US"
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                    request=request,
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
                request=request,
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id), request=request)

    result = SixGroupJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 3
    assert result.message == (
        "Scanned 3 SIX Switzerland vacancies from 3 catalog records across 2 page requests"
    )
    assert [request.url.path for request in requests] == [
        "/search/",
        "/search/",
        "/job/Zurich-Application-Engineer/101/",
        "/job/Zurich-Application-Engineer/102/",
        "/job/Zurich-Application-Engineer/103/",
    ]

    job = result.jobs[0]
    assert job.source == "six_group"
    assert job.title == "Application Engineer 101 (80 - 100%)"
    assert job.company == "SIX"
    assert job.location == "Zurich, CH"
    assert job.url == "https://jobs.six-group.test/job/Zurich-Application-Engineer/101/"
    assert job.apply_url == ("https://jobs.six-group.test/talentcommunity/apply/101/?locale=en_US")
    assert job.posted_at == "2026-08-13"
    assert job.employment_type == "80–100%"
    assert job.description == (
        "Application Engineer 101 (80 - 100%)\n\n"
        "SIX drives the transformation of financial markets.\n\n"
        "What You Will Do\n\n"
        "- Develop reliable financial applications.\n\n"
        "What You Bring\n\n"
        "- Experience with distributed systems."
    )
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["locations"] == ["Zurich, CH"]


def test_six_group_accepts_a_swiss_listing_location_among_detail_locations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                101,
                location="London, GB",
                additional_locations=("Madrid, ES", "Zurich, CH"),
            ),
            request=request,
        )

    job = (
        SixGroupJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description
    assert job.location == "Zurich, CH"
    assert job.raw["detail"]["locations"] == [
        "London, GB",
        "Madrid, ES",
        "Zurich, CH",
    ]


def test_six_group_retries_catalog_until_all_declared_ids_are_collected() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path == "/search/":
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                first_page_calls += 1
                ids = [101, 102] if first_page_calls == 1 else [101, 103]
                return httpx.Response(
                    200,
                    text=listing_html(ids, start=1, end=2, total=3),
                    request=request,
                )
            return httpx.Response(
                200,
                text=listing_html([101], start=3, end=3, total=3),
                request=request,
            )
        return httpx.Response(503, request=request)

    result = SixGroupJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_six_group_preserves_listing_when_detail_contract_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(101, company="Other Company"),
            request=request,
        )

    job = (
        SixGroupJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Application Engineer 101 (80 - 100%)"
    assert job.location == "Zurich, CH"
    assert job.description is None
    assert job.apply_url == ("https://jobs.six-group.test/talentcommunity/apply/101/?locale=en_US")
    assert "incomplete or non-Swiss vacancy" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (
            listing_html([101], start=1, end=1, total=1, location="Madrid, ES"),
            "non-Swiss vacancy",
        ),
        ("<html><body>Jobs</body></html>", "search results"),
        (listing_html([101, 101], start=1, end=2, total=2), "duplicate vacancy IDs"),
    ],
)
def test_six_group_rejects_invalid_catalogs(html: str, message: str) -> None:
    parser = SixGroupJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=html, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_six_group_enforces_catalog_page_limit_and_wraps_http_errors() -> None:
    too_large = SixGroupJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = SixGroupJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_six_group_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["six_group"]
    assert isinstance(parser, SixGroupJobsParser)
    assert parser.base_url == settings.six_group_jobs_base_url
    assert parser.max_pages == settings.six_group_jobs_max_pages
    assert parser.max_catalog_passes == settings.six_group_jobs_max_catalog_passes
    assert parser.detail_workers == settings.six_group_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SIX", "filters": {}},
            "sources": ["six_group", "six_group"],
        }
    )
    assert request.sources == ["six_group"]


def test_six_group_jobs_render_as_direct_company_imports() -> None:
    job = SixGroupJobsParser().normalize_job(
        {
            "id": "1415188733",
            "title": "Head Strategy & Business Development Securities Services",
            "location": "Zurich, CH",
            "url": ("https://jobs.six-group.com/job/Zurich-Head-Strategy/1415188733/"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="six_group-1415188733",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "SIX import"
    assert stored["company"] == "SIX"
    assert stored["applyUrl"] == (
        "https://jobs.six-group.com/talentcommunity/apply/1415188733/?locale=en_US"
    )
