from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.bachem import BachemJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def listing_html(
    ids: list[int],
    *,
    start: int,
    end: int,
    total: int,
    location: str = "Bubendorf, BL, CH, 4416",
) -> str:
    rows = "".join(
        f"""
        <tr class="data-row">
          <td class="colTitle">
            <a class="jobTitle-link"
               href="/job/Bubendorf-Batchdocument-Reviewer/{job_id}/">
              Batchdocument Reviewer {job_id}
            </a>
          </td>
          <td class="colDepartment">
            <span class="jobDepartment">Peptide Manufacturing</span>
          </td>
          <td class="colShifttype">
            <span class="jobShifttype">Unbefristet - vollzeit</span>
          </td>
          <td class="colLocation">
            <span class="jobLocation">{location}</span>
          </td>
          <td class="colDate">
            <span class="jobDate">Aug 11, 2026</span>
          </td>
        </tr>
        """
        for job_id in ids
    )
    return f"""
    <html><body>
      <table id="searchresults"
        aria-label="Search results for Switzerland. Results {start} to {end} of {total}">
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def detail_html(
    job_id: int,
    *,
    country: str = "CH",
    locality: str = "Bubendorf",
    region: str = "BL",
    postal_code: str = "4416",
    title: str | None = None,
    localized_title_markup: bool = False,
) -> str:
    job_title = title or f"Batchdocument Reviewer {job_id}"
    title_markup = (
        f'<h1 id="job-title" itemprop="title">{job_title}</h1>'
        if localized_title_markup
        else (f'<span itemprop="title" data-careersite-propertyid="title">{job_title}</span>')
    )
    return f"""
    <html><body>
      <div itemscope itemtype="http://schema.org/JobPosting">
        <meta itemprop="datePosted" content="Tue Aug 11 00:00:00 UTC 2026">
        <meta itemprop="validThrough" content="Tue Dec 01 23:00:00 UTC 2026">
        <meta itemprop="hiringOrganization" content="Bachem AG">
        <meta itemprop="addressLocality" content="{locality}">
        <meta itemprop="addressRegion" content="{region}">
        <meta itemprop="postalCode" content="{postal_code}">
        <meta itemprop="addressCountry" content="{country}">
        {title_markup}
        <span itemprop="description" data-careersite-propertyid="description">
          <span class="jobdescription">
            <style>.jobdescription {{ color: red; }}</style>
            <p>Review manufacturing documentation.</p>
            <ul><li>Ensure GMP compliance.</li></ul>
          </span>
        </span>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=de_DE">Apply now</a>
        <a class="dialogApplyBtn"
           href="/talentcommunity/apply/{job_id}/?locale=de_DE">Apply now</a>
      </div>
    </body></html>
    """


def test_bachem_scans_full_swiss_catalog_and_enriches_every_record() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/":
            assert request.url.params["optionsFacetsDD_country"] == "CH"
            offset = int(request.url.params.get("startrow", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    text=listing_html([101, 102], start=1, end=2, total=3),
                )
            return httpx.Response(
                200,
                text=listing_html([103], start=3, end=3, total=3),
            )
        job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
        return httpx.Response(200, text=detail_html(job_id))

    parser = BachemJobsParser(
        base_url=(
            "https://careers.bachem.test/search/?createNewAlert=false&q=&optionsFacetsDD_country=CH"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Bachem Switzerland vacancies from 3 catalog records across 2 page requests"
    )
    listing_requests = [request for request in requests if request.url.path == "/search/"]
    assert len(listing_requests) == 2
    assert listing_requests[0].url.params["locale"] == "en_US"
    assert listing_requests[0].url.params["sortColumn"] == "referencedate"
    assert listing_requests[1].url.params["startrow"] == "2"
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "bachem"
    assert first.title == "Batchdocument Reviewer 101"
    assert first.company == "Bachem AG"
    assert first.location == "Bubendorf, BL, CH, 4416"
    assert first.url == ("https://careers.bachem.test/job/Bubendorf-Batchdocument-Reviewer/101/")
    assert first.apply_url == (
        "https://careers.bachem.test/talentcommunity/apply/101/?locale=de_DE"
    )
    assert first.posted_at == "2026-08-11"
    assert first.employment_type == "Unbefristet - vollzeit"
    assert first.description == ("Review manufacturing documentation.\n\n- Ensure GMP compliance.")
    assert first.raw["category"] == "Peptide Manufacturing"
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["valid_through"] == "2026-12-01"


def test_bachem_repeats_shifted_pages_until_every_id_is_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.path != "/search/":
            job_id = int(request.url.path.rstrip("/").rsplit("/", maxsplit=1)[-1])
            return httpx.Response(200, text=detail_html(job_id))
        offset = int(request.url.params.get("startrow", "0"))
        if offset == 0:
            first_page_calls += 1
            return httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ids = [102] if first_page_calls == 1 else [103]
        return httpx.Response(200, text=listing_html(ids, start=3, end=3, total=3))

    result = BachemJobsParser(
        base_url="https://careers.bachem.test/search/",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert first_page_calls == 2
    assert result.message.endswith("across 4 page requests")


def test_bachem_preserves_listing_when_detail_is_not_swiss() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html([101], start=1, end=1, total=1),
            )
        return httpx.Response(200, text=detail_html(101, country="DE"))

    job = (
        BachemJobsParser(
            base_url="https://careers.bachem.test/search/",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Bubendorf, BL, CH, 4416"
    assert job.description is None
    assert job.apply_url == ("https://careers.bachem.test/talentcommunity/apply/101/?locale=en_US")
    assert "non-Swiss vacancy" in str(job.raw["detail_error"])


def test_bachem_supports_localized_detail_markup_and_region_abbreviation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(
                200,
                text=listing_html(
                    [101],
                    start=1,
                    end=1,
                    total=1,
                    location="Vionnaz, Valais, CH, 1895",
                ),
            )
        return httpx.Response(
            200,
            text=detail_html(
                101,
                locality="Vionnaz",
                region="Vala",
                postal_code="1895",
                localized_title_markup=True,
            ),
        )

    job = (
        BachemJobsParser(
            base_url="https://careers.bachem.test/search/",
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Batchdocument Reviewer 101"
    assert job.location == "Vionnaz, Valais, CH, 1895"
    assert job.description == ("Review manufacturing documentation.\n\n- Ensure GMP compliance.")


def test_bachem_rejects_non_swiss_listing() -> None:
    parser = BachemJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [101],
                    start=1,
                    end=1,
                    total=1,
                    location="Torrance, CA, US, 90503",
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())


def test_bachem_rejects_listing_without_catalog_contract() -> None:
    parser = BachemJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="search results"):
        parser.search(LinkedInSearchRequest())


def test_bachem_enforces_catalog_page_limit() -> None:
    parser = BachemJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html([101, 102], start=1, end=2, total=3),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_bachem_wraps_listing_request_failures() -> None:
    parser = BachemJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bachem_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bachem"]
    assert isinstance(parser, BachemJobsParser)
    assert parser.base_url == settings.bachem_jobs_base_url
    assert parser.max_pages == settings.bachem_jobs_max_pages
    assert parser.max_catalog_passes == settings.bachem_jobs_max_catalog_passes
    assert parser.detail_workers == settings.bachem_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bachem", "filters": {}},
            "sources": ["bachem", "bachem"],
        }
    )
    assert request.sources == ["bachem"]


def test_bachem_jobs_render_as_direct_company_imports() -> None:
    job = BachemJobsParser().normalize_job(
        {
            "id": "1425152933",
            "title": "Batchdocument Reviewer",
            "location": "Bubendorf, BL, CH, 4416",
            "url": ("https://careers.bachem.com/job/Bubendorf-Batchdocument-Reviewer/1425152933/"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="bachem-1425152933",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bachem import"
    assert stored["id"] == "bachem-1425152933"
