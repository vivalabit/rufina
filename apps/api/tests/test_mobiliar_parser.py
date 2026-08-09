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
from app.services.parsers.companies.mobiliar import MobiliarJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def landing_html() -> str:
    return """
    <html><head>
      <link rel="canonical" href="https://jobs.mobiliar.test/go/Jobs/506974/">
    </head><body>
      <script>
        var CSRFToken = "test-csrf-token";
        var appParams = { categoryId: "506974" };
      </script>
      <div id="jobSearch_searchGridComponent"></div>
    </body></html>
    """


def api_job(
    *,
    job_id: str,
    slug: str,
    title: str,
    location: str,
    workload: str,
    contract_type: str = "Unbefristet",
) -> dict[str, object]:
    return {
        "response": {
            "id": job_id,
            "unifiedUrlTitle": slug,
            "unifiedStandardTitle": title,
            "sfstd_marketingBrand_obj": ["die Mobiliar"],
            "jobLocationShort": [location],
            "cust_contractType": [contract_type],
            "cust_postingCatFTE": workload,
            "cust_postingDep": ["IT"],
            "cust_experienceLevel": ["Berufserfahrene"],
            "unifiedStandardStart": "06.07.26",
        }
    }


def api_payload(jobs: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {"jobSearchResult": jobs, "totalJobs": total}


def detail_html(
    *,
    job_id: str,
    slug: str,
    title: str,
    email_apply: bool = False,
) -> str:
    apply_markup = (
        ""
        if email_apply
        else f"""
        <a class="unify-apply-now" href="/talentcommunity/apply/{job_id}/?locale=de_DE">
          Jetzt bewerben
        </a>
        """
    )
    contact_markup = (
        '<a href="mailto:agency@mobiliar.test">agency@mobiliar.test</a>'
        if email_apply
        else "Contact the recruiter."
    )
    return f"""
    <html><head>
      <link rel="canonical"
            href="https://jobs.mobiliar.test/job/{slug}/{job_id}-de_DE/">
      <meta property="og:title" content="{title}">
    </head><body>
      <div class="jobDisplayShell" itemtype="http://schema.org/JobPosting">
        {apply_markup}
        <div class="joblayouttoken">
          <span class="rtltextaligneligible"><h1>{title}</h1><p>IT / Bern</p></span>
        </div>
        <div class="joblayouttoken">
          <span class="rtltextaligneligible">
            <h2>Das erwartet dich</h2>
            <p>Build resilient insurance platforms.</p>
            <h2>Das bewirkst du bei uns</h2>
            <ul><li>Operate critical services.</li><li>Coordinate stakeholders.</li></ul>
          </span>
        </div>
        <div class="joblayouttoken">
          <span itemprop="description" class="rtltextaligneligible">
            <h2>Neugierig?</h2><p>{contact_markup}</p>
          </span>
        </div>
      </div>
    </body></html>
    """


def test_mobiliar_scans_drifting_catalog_and_enriches_jobs() -> None:
    jobs = {
        "101": api_job(
            job_id="101",
            slug="platform-engineer",
            title="Platform Engineer (w/m/d)",
            location="Bern",
            workload="80% - 100%",
        ),
        "102": api_job(
            job_id="102",
            slug="data-engineer",
            title="Data Engineer (w/m/d)",
            location="Zürich",
            workload="100%",
        ),
        "103": api_job(
            job_id="103",
            slug="security-specialist",
            title="Security Specialist (w/m/d)",
            location="Nyon",
            workload="60 - 80%",
            contract_type="Befristet",
        ),
    }
    page_zero_calls = 0
    api_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page_zero_calls
        if request.method == "GET" and request.url.path == "/go/Jobs/506974/":
            return httpx.Response(200, text=landing_html())
        if request.method == "POST":
            api_requests.append(request)
            assert request.headers["x-csrf-token"] == "test-csrf-token"
            page_number = int(json.loads(request.content)["pageNumber"])
            if page_number == 0:
                page_zero_calls += 1
                return httpx.Response(
                    200,
                    json=api_payload([jobs["101"], jobs["102"]], total=3),
                )
            page_jobs = [jobs["102"]] if page_zero_calls == 1 else [jobs["103"]]
            return httpx.Response(200, json=api_payload(page_jobs, total=3))

        job_id = request.url.path.rsplit("/", maxsplit=2)[1].split("-", maxsplit=1)[0]
        item = jobs[job_id]["response"]
        assert isinstance(item, dict)
        return httpx.Response(
            200,
            text=detail_html(
                job_id=job_id,
                slug=str(item["unifiedUrlTitle"]),
                title=str(item["unifiedStandardTitle"]),
                email_apply=job_id == "103",
            ),
        )

    parser = MobiliarJobsParser(
        base_url="https://jobs.mobiliar.test/go/Jobs/506974/",
        api_url="https://jobs.mobiliar.test/services/recruiting/v1/jobs",
        max_pages=2,
        max_catalog_passes=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Mobiliar vacancies from 3 catalog records across 4 API requests"
    )
    assert len(api_requests) == 4
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "mobiliar"
    assert first.title == "Platform Engineer (w/m/d)"
    assert first.company == "die Mobiliar"
    assert first.location == "Bern"
    assert first.url == ("https://jobs.mobiliar.test/job/platform-engineer/101-de_DE/")
    assert first.apply_url == ("https://jobs.mobiliar.test/talentcommunity/apply/101/?locale=de_DE")
    assert first.posted_at == "2026-07-06"
    assert first.employment_type == "Unbefristet, 80%-100%"
    assert first.seniority == "Berufserfahrene"
    assert first.description == (
        "Das erwartet dich\n\n"
        "Build resilient insurance platforms.\n\n"
        "Das bewirkst du bei uns\n\n"
        "- Operate critical services.\n"
        "- Coordinate stakeholders."
    )
    assert first.raw["department"] == "IT"
    assert first.raw["detail"]["id"] == "101"
    assert result.jobs[2].employment_type == "Befristet, 60%-80%"
    assert result.jobs[2].apply_url == "mailto:agency@mobiliar.test"


def test_mobiliar_preserves_listing_when_detail_request_fails() -> None:
    job = api_job(
        job_id="101",
        slug="platform-engineer",
        title="Platform Engineer (w/m/d)",
        location="Bern",
        workload="80% - 100%",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go/Jobs/506974/":
            return httpx.Response(200, text=landing_html())
        if request.method == "POST":
            return httpx.Response(200, json=api_payload([job], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    parser = MobiliarJobsParser(
        base_url="https://jobs.mobiliar.test/go/Jobs/506974/",
        api_url="https://jobs.mobiliar.test/services/recruiting/v1/jobs",
        transport=httpx.MockTransport(handler),
    )

    parsed = parser.search(LinkedInSearchRequest()).jobs[0]

    assert parsed.title == "Platform Engineer (w/m/d)"
    assert parsed.location == "Bern"
    assert parsed.apply_url == parsed.url
    assert parsed.description is None
    assert "503 Service Unavailable" in str(parsed.raw["detail_error"])


def test_mobiliar_rejects_landing_page_without_catalog_contract() -> None:
    parser = MobiliarJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        parser.search(LinkedInSearchRequest())


def test_mobiliar_rejects_incomplete_api_vacancy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=landing_html())
        return httpx.Response(
            200,
            json=api_payload(
                [{"response": {"id": "101", "unifiedStandardTitle": "Engineer"}}],
                total=1,
            ),
        )

    parser = MobiliarJobsParser(transport=httpx.MockTransport(handler))

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_mobiliar_rejects_catalog_that_never_reaches_declared_total() -> None:
    job = api_job(
        job_id="101",
        slug="platform-engineer",
        title="Platform Engineer (w/m/d)",
        location="Bern",
        workload="100%",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=landing_html())
        return httpx.Response(200, json=api_payload([job], total=2))

    parser = MobiliarJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies"):
        parser.search(LinkedInSearchRequest())


def test_mobiliar_wraps_listing_request_failures() -> None:
    parser = MobiliarJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_mobiliar_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["mobiliar"]
    assert isinstance(parser, MobiliarJobsParser)
    assert parser.base_url == settings.mobiliar_jobs_base_url
    assert parser.api_url == settings.mobiliar_jobs_api_url
    assert parser.max_pages == settings.mobiliar_jobs_max_pages
    assert parser.max_catalog_passes == settings.mobiliar_jobs_max_catalog_passes
    assert parser.detail_workers == settings.mobiliar_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Mobiliar", "filters": {}},
            "sources": ["mobiliar", "mobiliar"],
        }
    )
    assert request.sources == ["mobiliar"]


def test_mobiliar_jobs_render_as_direct_company_imports() -> None:
    parser = MobiliarJobsParser()
    job = parser.normalize_job(
        {
            "id": "101",
            "title": "Platform Engineer (w/m/d)",
            "company": "die Mobiliar",
            "location": "Bern",
            "url": "https://jobs.mobiliar.ch/job/platform-engineer/101-de_DE/",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="mobiliar-101",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Mobiliar import"
    assert stored["id"] == "mobiliar-101"
