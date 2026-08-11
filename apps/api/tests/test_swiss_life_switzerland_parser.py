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
from app.services.parsers.companies.swiss_life_switzerland import (
    SwissLifeSwitzerlandJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOB_IDS = (
    "4c6b891f-22b1-494c-ad4e-06a25ede7ef4",
    "c641a757-42f5-453a-a2dd-d0643ebec8a9",
    "74bb0707-c0d6-4b3f-b74b-d52d8d8cec79",
)


def job_url(index: int) -> str:
    localized_paths = ("offene-stellen", "postes-vacantes", "posti-vacanti")
    return (
        f"https://jobs.swisslife.ch/{localized_paths[index]}/"
        f"customer-solution-architect-{index}/{JOB_IDS[index]}"
    )


def listing_html(
    indexes: list[int],
    *,
    total: int,
    offset: int,
    limit: int,
) -> str:
    page_number = (offset // limit) + 1
    cards = "".join(
        f"""
        <a class="job" href="{job_url(index)}">
          <div class="jobTitle">
            <h2>Customer Solution Architect {index}</h2>
            <span>Swiss Life AG</span>
          </div>
          <div class="jobArbeitsOrt"><svg></svg>Zürich</div>
        </a>
        """
        for index in indexes
    )
    return f"""
    <html><body>
      <form id="careercenter-form">
        <input name="offset" value="{offset}">
        <input name="limit" value="{limit}">
        <input name="lang" value="de">
      </form>
      <section id="jobs">
        <div class="anzStellen">{total} Stellen</div>
        {cards}
        <div id="pagination">
          <a class="button page active">{page_number}</a>
        </div>
      </section>
    </body></html>
    """


def detail_html(index: int, *, country: str = "Schweiz") -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": f"Customer Solution Architect {index}",
        "description": (
            "<h3>Dein Verantwortungsbereich</h3><ul>"
            "<li>Design data solutions</li><li>Guide customers</li></ul>"
        ),
        "datePosted": "2026-08-11",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": "Swiss Life AG"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": "Zürich",
            },
        },
    }
    return f"""
    <html><body>
      <a id="applyButton"
         href="https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[index]}/ats/">
        Jetzt bewerben
      </a>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </body></html>
    """


def test_swiss_life_collects_paginates_and_enriches_swiss_roles() -> None:
    requests: list[tuple[str, int | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            form = dict(item.split("=", 1) for item in request.content.decode().split("&"))
            offset = int(form["offset"])
            requests.append(("POST", offset))
            assert form["limit"] == "2"
            assert form["lang"] == "de"
            indexes = [0, 1] if offset == 0 else [2]
            return httpx.Response(
                200,
                text=listing_html(indexes, total=3, offset=offset, limit=2),
                request=request,
            )
        job_id = request.url.path.rstrip("/").split("/")[-1]
        index = JOB_IDS.index(job_id)
        requests.append(("GET", index))
        return httpx.Response(
            200,
            text=detail_html(index),
            request=request,
        )

    result = SwissLifeSwitzerlandJobsParser(
        page_size=2,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert requests == [
        ("POST", 0),
        ("POST", 2),
        ("GET", 0),
        ("GET", 1),
        ("GET", 2),
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Swiss Life Switzerland vacancies from 3 Prospective records "
        "across 2 page requests"
    )
    assert len(result.jobs) == 3
    job = result.jobs[0]
    assert job.source == "swiss_life_switzerland"
    assert job.title == "Customer Solution Architect 0"
    assert job.company == "Swiss Life AG"
    assert job.location == "Zürich, Switzerland"
    assert job.url == job_url(0)
    assert job.apply_url == (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[0]}/ats/")
    assert job.posted_at == "2026-08-11"
    assert job.employment_type == "Full-time"
    assert job.description == (
        "Dein Verantwortungsbereich\n- Design data solutions\n- Guide customers"
    )


def test_swiss_life_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                text=listing_html([0], total=1, offset=0, limit=200),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        SwissLifeSwitzerlandJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Customer Solution Architect 0"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_swiss_life_rejects_non_swiss_or_mismatched_detail() -> None:
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parse_detail_html(
            detail_html(0, country="Deutschland"),
            page_url=job_url(0),
            expected_job_id=JOB_IDS[0],
            expected_title="Customer Solution Architect 0",
        )
    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html(0),
            page_url=job_url(1),
            expected_job_id=JOB_IDS[0],
            expected_title="Customer Solution Architect 0",
        )


def test_swiss_life_rejects_incomplete_or_duplicate_catalog() -> None:
    incomplete = SwissLifeSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([0], total=2, offset=0, limit=200),
                request=request,
            )
        )
    )
    duplicate = SwissLifeSwitzerlandJobsParser(
        page_size=2,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(
                    [0, 0],
                    total=2,
                    offset=0,
                    limit=2,
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy page"):
        incomplete.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate.search(LinkedInSearchRequest())


def test_swiss_life_rejects_oversized_catalog() -> None:
    parser = SwissLifeSwitzerlandJobsParser(
        page_size=2,
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([0, 1], total=3, offset=0, limit=2),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_swiss_life_wraps_listing_request_failures() -> None:
    parser = SwissLifeSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_swiss_life_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["swiss_life_switzerland"]
    assert isinstance(parser, SwissLifeSwitzerlandJobsParser)
    assert parser.base_url == settings.swiss_life_switzerland_jobs_base_url
    assert parser.catalog_url == settings.swiss_life_switzerland_jobs_catalog_url
    assert parser.max_pages == settings.swiss_life_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.swiss_life_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Swiss Life Switzerland", "filters": {}},
            "sources": ["swiss_life_switzerland", "swiss_life_switzerland"],
        }
    )
    assert request.sources == ["swiss_life_switzerland"]


def test_swiss_life_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": JOB_IDS[0],
        "title": "Customer Solution Architect 0",
        "company": "Swiss Life AG",
        "location": "Zürich",
        "url": job_url(0),
        "detail": {
            "title": "Customer Solution Architect 0",
            "apply_url": (f"https://ohws.prospective.ch/public/v1/redirect/{JOB_IDS[0]}/ats/"),
            "posted_at": "2026-08-11",
            "employment_type": "FULL_TIME",
            "description": "Design data solutions.",
        },
    }
    job = SwissLifeSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"swiss_life_switzerland-{JOB_IDS[0]}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Swiss Life Switzerland import"
    assert stored["id"] == f"swiss_life_switzerland-{JOB_IDS[0]}"
