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
from app.services.parsers.companies.ruag_switzerland import (
    RuagSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOB_ONE_ID = "24e02ed3-4dc6-4358-a9f4-9383b380371b"
JOB_TWO_ID = "99aa0e68-5f31-4f26-99bb-496a3952a64f"


def listing_card(
    *,
    job_id: str,
    slug: str,
    title: str,
    city: str,
    country: str = "Schweiz",
    workload: str = "100%",
) -> str:
    return f"""
    <a href="https://jobs.ruag.ch/offene-stellen/{slug}/{job_id}"
       class="ruag-c-result-list-item" target="_blank">
      <div class="ruag-c-result-list-item__text">
        <h3 class="ruag-c-result-list-item__title">
          <span>{title}</span><span>m/f/d</span>
        </h3>
        <div class="ruag-c-result-list-item__facts">
          <p class="ruag-c-result-list-item__fact">Berufserfahrene</p>
          <p class="ruag-c-result-list-item__fact">{city}</p>
          <p class="ruag-c-result-list-item__fact">{country}</p>
          <p class="ruag-c-result-list-item__fact">{workload}</p>
        </div>
      </div>
    </a>
    """


def listing_page(cards: list[str], *, page: int = 0, total: int | None = None) -> str:
    total = len(cards) if total is None else total
    start = page * 20 + 1
    end = start + len(cards) - 1
    return f"""
    <html><body>
      <form id="views-exposed-form-jobfilter-block-1"></form>
      <div id="job-results">
        <div class="ruag-c-filtered-view">
          <div class="ruag-c-filtered-view__view">
            <h3>{total} Results found</h3>
            <div class="ruag-c-result-list">{"".join(cards)}</div>
          </div>
        </div>
        <footer class="ruag-o-pagination">
          <div class="ruag-o-pagination__count">{start}-{end} of {total} results</div>
          <ul><li class="pager__item is-active"><span>{page + 1}</span></li></ul>
        </footer>
      </div>
    </body></html>
    """


def detail_page(
    *,
    job_id: str,
    title: str,
    city: str,
    country: str = "Schweiz",
    organization: str = "RUAG AG",
) -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<h2>Das kannst du bewegen</h2>"
            "<ul><li>Sichere kritische Systeme</li><li>Arbeite im Team</li></ul>"
        ),
        "datePosted": "2026-08-10",
        "validThrough": "2053-12-24",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": organization},
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
      <div id="jobTitle"><h1>{title} (w/m/d)</h1></div>
      <a title="Bewerben Sie sich"
         href="https://jobs.ruag.ch/apply/ats/{job_id}">Jetzt bewerben</a>
    </body></html>
    <script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_ruag_scans_catalog_through_cookie_check_and_enriches_details() -> None:
    challenged = False
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal challenged
        requests.append(str(request.url))
        if request.url.host == "www.ruag.ch" and request.url.path.startswith(
            "/cookie-check-"
        ):
            assert "AL_CHK-S=challenge" in request.headers["cookie"]
            challenged = True
            return httpx.Response(
                302,
                headers={
                    "location": "/en/working-us/job-portal",
                    "set-cookie": "ncs-S=verified; Path=/; Secure; HttpOnly",
                },
            )
        if request.url.host == "www.ruag.ch":
            assert "Chrome/123.0" in request.headers["user-agent"]
            assert "text/html" in request.headers["accept"]
            if not challenged:
                return httpx.Response(
                    307,
                    headers={
                        "location": "/cookie-check-d973?l=%2Fen%2Fworking-us%2Fjob-portal",
                        "set-cookie": "AL_CHK-S=challenge; Path=/; Secure; HttpOnly",
                    },
                )
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id=JOB_ONE_ID,
                            slug="helikoptermechaniker-ec-635",
                            title="Helikoptermechaniker EC-635",
                            city="Alpnach",
                        ),
                        listing_card(
                            job_id=JOB_TWO_ID,
                            slug="senior-network-engineer",
                            title="Senior Network Engineer",
                            city="Wangen",
                            workload="80–100%",
                        ),
                    ]
                ),
            )
        if request.url.path.endswith(JOB_ONE_ID):
            return httpx.Response(
                200,
                text=detail_page(
                    job_id=JOB_ONE_ID,
                    title="Helikoptermechaniker EC-635",
                    city="Alpnach",
                ),
            )
        if request.url.path.endswith(JOB_TWO_ID):
            return httpx.Response(
                200,
                text=detail_page(
                    job_id=JOB_TWO_ID,
                    title="Senior Network Engineer",
                    city="Wangen",
                    organization="C5I",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = RuagSwitzerlandJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 5
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 RUAG Switzerland vacancies across 1 catalog pages "
        "in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "ruag_switzerland"
    assert first.title == "Helikoptermechaniker EC-635 (w/m/d)"
    assert first.company == "RUAG AG"
    assert first.location == "Alpnach, Schweiz"
    assert first.url and first.url.endswith(JOB_ONE_ID)
    assert first.apply_url == f"https://jobs.ruag.ch/apply/ats/{JOB_ONE_ID}"
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "100%, Full-time"
    assert first.seniority == "Berufserfahrene"
    assert first.description and "kritische Systeme" in first.description
    assert first.description and "- Arbeite im Team" in first.description
    assert first.raw["country"] == "Schweiz"
    assert first.raw["detail"]["valid_through"] == "2053-12-24"
    assert result.jobs[1].company == "C5I"


def test_ruag_retries_when_catalog_changes_during_pagination() -> None:
    pass_number = 0

    def make_card(index: int) -> str:
        job_id = f"{index:08x}-0000-4000-8000-{index:012x}"
        return listing_card(
            job_id=job_id,
            slug=f"job-{index}",
            title=f"Job {index}",
            city="Bern",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pass_number
        page = int(request.url.params.get("page", "0"))
        if page == 0:
            pass_number += 1
            return httpx.Response(
                200,
                text=listing_page([make_card(i) for i in range(20)], total=21),
            )
        total = 22 if pass_number == 1 else 21
        cards = [make_card(20), make_card(21)] if total == 22 else [make_card(20)]
        return httpx.Response(
            200,
            text=listing_page(cards, page=1, total=total),
        )

    class ListingOnlyParser(RuagSwitzerlandJobsParser):
        def enrich_records(
            self,
            client: httpx.Client,
            records: list[dict[str, object]],
        ) -> None:
            return None

    result = ListingOnlyParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert pass_number == 2
    assert len(result.jobs) == 21
    assert "across 4 catalog pages in 2 catalog pass(es)" in (result.message or "")


def test_ruag_preserves_swiss_listing_when_detail_fails_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.ruag.ch":
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            job_id=JOB_ONE_ID,
                            slug="helikoptermechaniker-ec-635",
                            title="Helikoptermechaniker EC-635",
                            city="Alpnach",
                        )
                    ]
                ),
            )
        return httpx.Response(
            200,
            text=detail_page(
                job_id=JOB_ONE_ID,
                title="Helikoptermechaniker EC-635",
                city="Berlin",
                country="Deutschland",
            ),
        )

    job = (
        RuagSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Helikoptermechaniker EC-635"
    assert job.location == "Alpnach, Schweiz"
    assert job.apply_url and job.apply_url.endswith(JOB_ONE_ID)
    assert job.description is None
    assert "required vacancy data" in str(job.raw["detail_error"])


def test_ruag_rejects_listing_with_non_swiss_card() -> None:
    page = listing_page(
        [
            listing_card(
                job_id=JOB_ONE_ID,
                slug="foreign-job",
                title="Foreign job",
                city="Berlin",
                country="Deutschland",
            )
        ]
    )
    parser = RuagSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        parser.search(LinkedInSearchRequest())


def test_ruag_rejects_non_official_catalog_url() -> None:
    parser = RuagSwitzerlandJobsParser(
        base_url="https://www.ruag.ch/en/working-us/job-portal?page=1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="")),
    )

    with pytest.raises(DirectCompanyRequestError, match="official unfiltered listing"):
        parser.search(LinkedInSearchRequest())


def test_ruag_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ruag_switzerland"]
    assert isinstance(parser, RuagSwitzerlandJobsParser)
    assert parser.base_url == settings.ruag_switzerland_jobs_base_url
    assert parser.max_pages == settings.ruag_switzerland_jobs_max_pages
    assert (
        parser.max_catalog_passes
        == settings.ruag_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == settings.ruag_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "RUAG", "filters": {}},
            "sources": ["ruag_switzerland", "ruag_switzerland"],
        }
    )
    assert request.sources == ["ruag_switzerland"]


def test_ruag_jobs_render_as_direct_company_imports() -> None:
    parser = RuagSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": JOB_ONE_ID,
            "title": "Helikoptermechaniker EC-635",
            "location": "Alpnach, Schweiz",
            "url": (
                "https://jobs.ruag.ch/offene-stellen/helikoptermechaniker-ec-635/"
                f"{JOB_ONE_ID}"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"ruag_switzerland-{JOB_ONE_ID}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "RUAG Switzerland import"
    assert stored["id"] == f"ruag_switzerland-{JOB_ONE_ID}"
