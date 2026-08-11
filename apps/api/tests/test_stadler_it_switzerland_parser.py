from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.stadler_it_switzerland import (
    StadlerItSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(
    job_id: int,
    title: str,
    location: str,
    *,
    categories: tuple[str, ...] = ("Informatik",),
) -> str:
    slug = f"job-{job_id}"
    detail_url = f"https://jobs.stadlerrail.ch/offene-stellen/informatik/{slug}/uuid-{job_id}"
    category_html = "".join(f'<span class="item">{category}</span><br>' for category in categories)
    return f"""
    <div class="platform-item" id="job-{job_id}" title="{title}"
         job-href="{detail_url}"
         data-href="http://jobs.stadlerrail.ch/apply?id={job_id}">
      <div class="itemlist_jobtitle">
        <a href="{detail_url}" title="{title} – {location}">{title} – {location}</a>
      </div>
      <div class="itemlist_text">{category_html}</div>
    </div>
    """


def listing_page(
    cards: list[str],
    *,
    total: int,
    current_page: int,
    total_pages: int,
    it_selected: bool = True,
    switzerland_selected: bool = True,
) -> str:
    return f"""
    <html><body>
      <form id="oh-form" method="post">
        <select name="filter_10">
          <option value="1077445" {"selected" if it_selected else ""}>Informatik</option>
        </select>
        <select name="filter_25">
          <option value="1098730" {"selected" if switzerland_selected else ""}>Schweiz</option>
        </select>
      </form>
      <div id="recordcount">Offene Stellen: {total}</div>
      <div id="itemlist">{"".join(cards)}</div>
      <div id="pagination"><strong>{current_page} von {total_pages}</strong></div>
    </body></html>
    """


def detail_page(
    title: str,
    *,
    city: str,
    country: str = "Schweiz",
    workload: str = "80-100%",
    contract_type: str = "unbefristet",
    posted_at: str = "2026-07-30",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<h3>Gestalte die digitale Mobilität.</h3><br>"
            "<ul><li>Entwickle robuste Plattformen</li>"
            "<li>Arbeite mit internationalen Teams</li></ul>"
        ),
        "datePosted": posted_at,
        "validThrough": "2036-07-27",
        "employmentType": "PART_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Stadler Service AG",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": city,
            },
        },
    }
    return f"""
    <html><body>
      <section id="introduction">
        <ul class="meta">
          <li><span>{city}, {country}</span></li>
          <li><span>{workload}</span></li>
          <li><span>{contract_type}</span></li>
        </ul>
      </section>
      <a class="button apply" href="/public/v1/redirect/job/ats/">Jetzt bewerben</a>
    </body></html>
    <script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_stadler_scans_all_filtered_pages_and_enriches_details() -> None:
    listing_offsets: list[str] = []
    detail_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ohws.prospective.test":
            assert request.method == "POST"
            form = parse_qs(request.content.decode())
            assert form["filter_10"] == ["1077445"]
            assert form["filter_25"] == ["1098730"]
            assert form["lang"] == ["de"]
            assert form["limit"] == ["2"]
            offset = form["offset"][0]
            listing_offsets.append(offset)
            if offset == "0":
                return httpx.Response(
                    200,
                    text=listing_page(
                        [
                            listing_card(101, "DevOps & Integration Engineer", "Frauenfeld"),
                            listing_card(102, "AI DevOps Engineer", "Bussnang"),
                        ],
                        total=3,
                        current_page=1,
                        total_pages=2,
                    ),
                )
            if offset == "2":
                return httpx.Response(
                    200,
                    text=listing_page(
                        [
                            listing_card(
                                103,
                                "Initiativbewerbung für Studierende",
                                "Bussnang",
                                categories=("Engineering", "Informatik"),
                            )
                        ],
                        total=3,
                        current_page=2,
                        total_pages=2,
                    ),
                )
        if request.url.host == "jobs.stadlerrail.ch":
            detail_paths.append(request.url.path)
            job_id = request.url.path.rstrip("/").split("-")[-1]
            title = {
                "101": "DevOps &amp; Integration Engineer",
                "102": "AI DevOps Engineer",
                "103": "Initiativbewerbung für Studierende",
            }[job_id]
            city = "Frauenfeld" if job_id == "101" else "Bussnang"
            return httpx.Response(200, text=detail_page(title, city=city))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    result = StadlerItSwitzerlandJobsParser(
        base_url="https://www.stadlerrail.test/de/karriere/offene-stellen?10=1077445&25=1098730&",
        catalog_url="https://ohws.prospective.test/public/v1/careercenter/1000470/",
        page_size=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert listing_offsets == ["0", "2"]
    assert len(detail_paths) == 3
    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Stadler IT Switzerland vacancies across 2 Prospective pages "
        "in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "stadler_it_switzerland"
    assert first.title == "DevOps & Integration Engineer"
    assert first.company == "Stadler"
    assert first.location == "Frauenfeld, Schweiz"
    assert first.url and first.url.endswith("uuid-101")
    assert first.apply_url == "https://jobs.stadlerrail.ch/public/v1/redirect/job/ats/"
    assert first.posted_at == "2026-07-30"
    assert first.employment_type == "80-100%, unbefristet, Part-time"
    assert first.description and "Gestalte die digitale Mobilität" in first.description
    assert first.description and "- Entwickle robuste Plattformen" in first.description
    assert first.raw["categories"] == ["Informatik"]
    assert result.jobs[2].title == "Initiativbewerbung für Studierende"


def test_stadler_preserves_filtered_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ohws.prospective.ch":
            return httpx.Response(
                200,
                text=listing_page(
                    [listing_card(201, "Cloud Engineer Azure", "Wallisellen")],
                    total=1,
                    current_page=1,
                    total_pages=1,
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        StadlerItSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Cloud Engineer Azure"
    assert job.location == "Wallisellen"
    assert job.description is None
    assert job.apply_url == "https://jobs.stadlerrail.ch/apply?id=201"
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_stadler_rejects_listing_without_exact_filters() -> None:
    page = listing_page(
        [],
        total=0,
        current_page=1,
        total_pages=1,
        switzerland_selected=False,
    )
    parser = StadlerItSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="official IT and Switzerland filters"):
        parser.search(LinkedInSearchRequest())


def test_stadler_rejects_non_it_listing_record() -> None:
    page = listing_page(
        [listing_card(301, "Production Manager", "Bussnang", categories=("Produktion",))],
        total=1,
        current_page=1,
        total_pages=1,
    )
    parser = StadlerItSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="non-IT vacancy"):
        parser.search(LinkedInSearchRequest())


def test_stadler_enforces_catalog_page_limit() -> None:
    page = listing_page(
        [listing_card(401, "Directory Service Engineer", "Bussnang")],
        total=3,
        current_page=1,
        total_pages=3,
    )
    parser = StadlerItSwitzerlandJobsParser(
        max_pages=1,
        page_size=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_stadler_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["stadler_it_switzerland"]
    assert isinstance(parser, StadlerItSwitzerlandJobsParser)
    assert parser.base_url == settings.stadler_it_switzerland_jobs_base_url
    assert parser.catalog_url == settings.stadler_it_switzerland_jobs_catalog_url
    assert parser.max_pages == settings.stadler_it_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.stadler_it_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Stadler IT", "filters": {}},
            "sources": ["stadler_it_switzerland", "stadler_it_switzerland"],
        }
    )
    assert request.sources == ["stadler_it_switzerland"]


def test_stadler_jobs_render_as_direct_company_imports() -> None:
    parser = StadlerItSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "10133279",
            "title": "DevOps & Integration Engineer",
            "location": "Frauenfeld",
            "url": "https://jobs.stadlerrail.ch/offene-stellen/informatik/devops/uuid",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="stadler_it_switzerland-10133279",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Stadler IT Switzerland import"
    assert stored["id"] == "stadler_it_switzerland-10133279"
