from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.huber_suhner_switzerland import (
    HuberSuhnerSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def location_filter() -> str:
    return """
    <select name="searchSkill1004">
      <option>Deutschland</option>
      <option>&gt; Unterhaching</option>
      <option>Schweiz</option>
      <option>&gt; Herisau (AR)</option>
      <option>&gt; Pfäffikon (ZH)</option>
      <option>United States of America</option>
      <option>&gt; Warren, NJ</option>
    </select>
    """


def listing_card(
    job_id: int,
    title: str,
    location: str,
    *,
    language_id: int = 1,
    posted_at: str = "08.07.2026",
) -> str:
    return f"""
    <tr class="tableaslist_contentrow1">
      <td class="tableaslist_cell">
        <div class="tableaslist_cell">
          <span class="tableaslist_text tableaslist_element_1152487">
            Online seit: {posted_at}<br />
          </span>
          <span class="tableaslist_subtitle tableaslist_element_1152488">
            <a href="/Vacancies/{job_id}/Description/{language_id}"
               class="HSTableLinkSubTitle">{title}</a>
          </span>
          <span class="tableaslist_subtitle tableaslist_element_1152490">
            | Stellennummer: {job_id}
          </span>
          <span class="tableaslist_subtitle tableaslist_element_1152495">
            | {location}
          </span>
        </div>
      </td>
    </tr>
    """


def listing_page(cards: list[str], *, next_href: str | None) -> str:
    pagination = (
        f'<span data-pagination-next-href="{next_href}"></span>'
        if next_href
        else "<span></span>"
    )
    page_size = len(cards) if next_href else 50
    return f"""
    <html><body>
      {location_filter()}
      {pagination}
      <div data-one-item-chunk="{page_size}">
        <table class="tableaslist"><tbody>{"".join(cards)}</tbody></table>
      </div>
    </body></html>
    """


def detail_page(
    job_id: int,
    title: str,
    *,
    location: str,
    workload: str = "100%",
    contract_type: str = "Unbefristet",
    apply_href: str | None = None,
) -> str:
    apply_href = apply_href or f"/Vacancies/{job_id}/Application/CheckLogin/1?lang=ger"
    return f"""
    <html><body>
      <section class="section"><article>
        <header class="section__header">
          <h1>{title}</h1>
          <p class="section__header__subtitle">
            <span>m/w/d</span> | <span>{location}</span> |
            <span>{workload}</span> | <span>{contract_type}</span>
          </p>
        </header>
        <main class="section__main">
          <section>
            <h4>Ihr Aufgabengebiet</h4>
            <p>Sie entwickeln zuverlässige Verbindungslösungen.</p>
            <ul><li>Produkte gestalten</li><li>Teams beraten</li></ul>
          </section>
          <a href="{apply_href}">Jetzt bewerben</a>
        </main>
      </article></section>
    </body></html>
    """


def test_huber_suhner_scans_all_pages_filters_switzerland_and_enriches_details() -> None:
    listing_requests: list[str] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Jobs/All":
            listing_requests.append(str(request.url))
            if request.url.params.get("tc1152481") == "p2":
                return httpx.Response(
                    200,
                    text=listing_page(
                        [
                            listing_card(
                                7807,
                                "Global Product Manager",
                                "Unterhaching, Pfäffikon (ZH)",
                                posted_at="07.07.2026",
                            )
                        ],
                        next_href=None,
                    ),
                )
            return httpx.Response(
                200,
                text=listing_page(
                    [
                        listing_card(
                            7806,
                            "Corporate Controller",
                            "Pfäffikon (ZH)",
                            posted_at="08/10/2026",
                        ),
                        listing_card(8081, "Logistics Clerk", "Warren, NJ"),
                    ],
                    next_href=(
                        "?tc1152481=p2&amp;_search_token1152481=2010155459"
                        "#connectortable_1152481"
                    ),
                ),
            )
        if request.url.path == "/Vacancies/7806/Description/1":
            detail_requests.append(request.url.path)
            return httpx.Response(
                200,
                text=detail_page(
                    7806,
                    "Corporate Controller",
                    location="Pfäffikon (ZH)",
                ),
            )
        if request.url.path == "/Vacancies/7807/Description/1":
            detail_requests.append(request.url.path)
            return httpx.Response(
                200,
                text=detail_page(
                    7807,
                    "Global Product Manager",
                    location="Pfäffikon (ZH)",
                    workload="80-100%",
                    apply_href="https://recruiter.test/jobs/global-product-manager",
                ),
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    result = HuberSuhnerSwitzerlandJobsParser(
        base_url="https://huber.test/Jobs/All",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(listing_requests) == 2
    assert "tc1152481=p2" in listing_requests[1]
    assert "_search_token1152481=2010155459" in listing_requests[1]
    assert set(detail_requests) == {
        "/Vacancies/7806/Description/1",
        "/Vacancies/7807/Description/1",
    }
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Huber+Suhner Switzerland vacancies from 3 global catalog "
        "records across 2 Umantis pages"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "huber_suhner_switzerland"
    assert first.title == "Corporate Controller"
    assert first.company == "Huber+Suhner"
    assert first.location == "Pfäffikon (ZH)"
    assert first.url == "https://huber.test/Vacancies/7806/Description/1"
    assert first.apply_url == (
        "https://huber.test/Vacancies/7806/Application/CheckLogin/1?lang=ger"
    )
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "100%, Unbefristet"
    assert first.description and "Ihr Aufgabengebiet" in first.description
    assert first.description and "- Produkte gestalten" in first.description
    assert "Jetzt bewerben" not in first.description
    assert first.raw["listing_page"] == 1
    assert first.raw["swiss_location_catalog"] == ["Herisau (AR)", "Pfäffikon (ZH)"]
    assert result.jobs[1].employment_type == "80-100%, Unbefristet"
    assert result.jobs[1].apply_url == (
        "https://recruiter.test/jobs/global-product-manager"
    )


def test_huber_suhner_preserves_swiss_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Jobs/All":
            return httpx.Response(
                200,
                text=listing_page(
                    [listing_card(7456, "Produktionskoordinator", "Herisau (AR)")],
                    next_href=None,
                ),
            )
        return httpx.Response(503, text="temporarily unavailable")

    job = HuberSuhnerSwitzerlandJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Produktionskoordinator"
    assert job.location == "Herisau (AR)"
    assert job.posted_at == "2026-07-08"
    assert job.description is None
    assert job.apply_url is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_huber_suhner_rejects_listing_without_swiss_location_filter() -> None:
    page = """
    <html><body>
      <div data-one-item-chunk="50">
        <table class="tableaslist"><tbody></tbody></table>
      </div>
    </body></html>
    """
    parser = HuberSuhnerSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="Swiss location filter"):
        parser.search(LinkedInSearchRequest())


def test_huber_suhner_rejects_incomplete_listing_record() -> None:
    incomplete = listing_card(7806, "Corporate Controller", "").replace(
        "Online seit: 08.07.2026",
        "",
    )
    parser = HuberSuhnerSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_page([incomplete], next_href=None),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_huber_suhner_enforces_catalog_page_limit() -> None:
    page = listing_page(
        [listing_card(7806, "Corporate Controller", "Pfäffikon (ZH)")],
        next_href="?tc1152481=p2&_search_token1152481=123",
    )
    parser = HuberSuhnerSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_huber_suhner_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["huber_suhner_switzerland"]
    assert isinstance(parser, HuberSuhnerSwitzerlandJobsParser)
    assert parser.base_url == settings.huber_suhner_switzerland_jobs_base_url
    assert parser.max_pages == settings.huber_suhner_switzerland_jobs_max_pages
    assert parser.detail_workers == settings.huber_suhner_switzerland_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Huber+Suhner", "filters": {}},
            "sources": ["huber_suhner_switzerland", "huber_suhner_switzerland"],
        }
    )
    assert request.sources == ["huber_suhner_switzerland"]


def test_huber_suhner_jobs_render_as_direct_company_imports() -> None:
    parser = HuberSuhnerSwitzerlandJobsParser()
    job = parser.normalize_job(
        {
            "id": "7806",
            "title": "Corporate Controller",
            "location": "Pfäffikon (ZH)",
            "url": "https://recruiting.hubersuhner.com/Vacancies/7806/Description/1",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="huber_suhner_switzerland-7806",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Huber+Suhner Switzerland import"
    assert stored["id"] == "huber_suhner_switzerland-7806"
