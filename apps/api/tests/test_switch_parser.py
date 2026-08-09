from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.switch import SwitchJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def listing_card(
    job_id: int,
    title: str,
    *,
    job_type: str = "Teilzeit",
    contract_type: str = "unbefristet",
    department: str = "Cloud",
) -> str:
    return f"""
    <tr class="table-as-list__contentrow1">
      <td class="table-as-list__cell">
        <ul class="table-cell-content" aria-label="Stellendetails">
          <li><h3><a class="HSTableLinkSubTitle"
            href="/Vacancies/{job_id}/Description/1">{title}</a></h3></li>
          <li class="form_content_paragraph">
            <span class="column-value">Switch</span>
          </li>
          <li class="form_content_paragraph">
            <span class="visually-hidden">Art</span>
            <span class="column-value">{job_type}</span>
          </li>
          <li class="form_content_paragraph">
            <span class="visually-hidden">Befristung</span>
            <span class="column-value">{contract_type}</span>
          </li>
          <li class="form_content_paragraph">
            <span class="visually-hidden">Unternehmensbereich</span>
            <span class="column-value">{department}</span>
          </li>
        </ul>
      </td>
    </tr>
    """


def listing_page(
    cards: list[str],
    *,
    total: int,
    next_href: str | None,
    render_visible_count: bool = True,
) -> str:
    next_link = (
        f'<a class="HSTableNavigation load-next" aria-label="nächste" href="{next_href}">next</a>'
        if next_href
        else '<a class="HSTableNavigation load-next disabled" aria-label="nächste" '
        'aria-disabled="true" disabled="disabled" href="?tc=p2">next</a>'
    )
    return f"""
    <html><body>
      <h3 class="jobs-counter">
        <span class="total-number">{total if render_visible_count else ""}</span>
        <span class="jobs-text">Stellen gefunden</span>
      </h3>
      <table-navigation initial-data-string='{{"TableTotalLines":"{total}"}}'>
      </table-navigation>
      <table aria-label="Liste Stellenübersicht"><tbody>{"".join(cards)}</tbody></table>
      {next_link}
    </body></html>
    """


def detail_page(title: str, job_id: int) -> str:
    return f"""
    <html><body>
      <div id="mg_template"><div class="content">
        <h1>{title}</h1>
        <p>Switch ist die Digitalisierungspartnerin der Schweizer Hochschulen.</p>
        <div>Dein Team und deine Arbeit</div>
        <p>Du entwickelst verlässliche digitale Dienste.</p>
        <ul><li>Dokumentationen erstellen</li><li>Services betreiben</li></ul>
        <a href="/Vacancies/{job_id}/Application/CheckLogin/1">Jetzt bewerben</a>
      </div></div>
    </body></html>
    """


def test_switch_follows_umantis_pagination_and_enriches_details() -> None:
    first_title = (
        "Technical Documentation Specialist (60% - all identities and backgrounds*) in Zürich"
    )
    second_title = "Network & Security Engineer (80-100% - all identities)"
    listing_requests: list[str] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Jobs/1":
            listing_requests.append(str(request.url))
            if request.url.params.get("tc66856") == "p2":
                return httpx.Response(
                    200,
                    text=listing_page(
                        [listing_card(556, second_title, department="IT Services")],
                        total=2,
                        next_href=None,
                    ),
                )
            return httpx.Response(
                200,
                text=listing_page(
                    [listing_card(557, first_title, department="Trust & Identity")],
                    total=2,
                    next_href="?tc66856=p2&_search_token66856=123#connectortable_66856",
                ),
            )
        if "/Vacancies/" in request.url.path:
            detail_requests.append(str(request.url))
            job_id = int(request.url.path.split("/")[2])
            title = first_title if job_id == 557 else second_title
            return httpx.Response(200, text=detail_page(title, job_id))
        return httpx.Response(404)

    parser = SwitchJobsParser(
        base_url="https://switch.test/Jobs/1?lang=ger",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(listing_requests) == 2
    assert "tc66856=p2" in listing_requests[1]
    assert len(detail_requests) == 2
    assert all("lang=ger" in url for url in detail_requests)
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Switch vacancies from 2 catalog records across 2 Umantis page requests"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "switch"
    assert first.title == first_title
    assert first.company == "Switch"
    assert first.location == "Zürich"
    assert first.url == "https://switch.test/Vacancies/557/Description/1?lang=ger"
    assert first.apply_url == (
        "https://switch.test/Vacancies/557/Application/CheckLogin/1?lang=ger"
    )
    assert first.employment_type == "Teilzeit, 60%, unbefristet"
    assert first.description and "Dein Team und deine Arbeit" in first.description
    assert "- Dokumentationen erstellen" in first.description
    assert first_title not in first.description
    assert "Jetzt bewerben" not in first.description
    assert first.raw["department"] == "Trust & Identity"
    assert first.raw["listing_page"] == 1
    assert first.raw["detail"]["apply_url"] == first.apply_url


def test_switch_preserves_listing_when_detail_request_fails() -> None:
    title = "Product Owner Switch Cloud Portal (80-100%) in Zürich"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Jobs/1":
            return httpx.Response(
                200,
                text=listing_page([listing_card(556, title)], total=1, next_href=None),
            )
        return httpx.Response(503, text="temporarily unavailable")

    parser = SwitchJobsParser(transport=httpx.MockTransport(handler))
    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == title
    assert job.location == "Zürich"
    assert job.employment_type == "Teilzeit, 80–100%, unbefristet"
    assert job.description is None
    assert job.apply_url is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_switch_reads_count_from_umantis_web_component_before_javascript() -> None:
    title = "Product Owner Switch Cloud Portal (80-100%) in Zürich"
    page = listing_page(
        [listing_card(556, title)],
        total=1,
        next_href=None,
        render_visible_count=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Jobs/1":
            return httpx.Response(200, text=page)
        return httpx.Response(200, text=detail_page(title, 556))

    parser = SwitchJobsParser(transport=httpx.MockTransport(handler))

    assert len(parser.search(LinkedInSearchRequest()).jobs) == 1


def test_switch_rejects_listing_without_vacancy_count() -> None:
    parser = SwitchJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Jobs</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy count"):
        parser.search(LinkedInSearchRequest())


def test_switch_rejects_incomplete_catalog() -> None:
    page = listing_page(
        [listing_card(557, "Technical Writer (60%) in Zürich")],
        total=2,
        next_href=None,
    )
    parser = SwitchJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    )

    with pytest.raises(DirectCompanyRequestError, match="declared 2"):
        parser.search(LinkedInSearchRequest())


def test_switch_enforces_catalog_page_limit() -> None:
    page = listing_page(
        [listing_card(557, "Technical Writer (60%) in Zürich")],
        total=2,
        next_href="?tc66856=p2&_search_token66856=123",
    )
    parser = SwitchJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser.search(LinkedInSearchRequest())


def test_switch_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["switch"]
    assert isinstance(parser, SwitchJobsParser)
    assert parser.base_url == settings.switch_jobs_base_url
    assert parser.max_pages == settings.switch_jobs_max_pages
    assert parser.detail_workers == settings.switch_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Switch", "filters": {}},
            "sources": ["switch", "switch"],
        }
    )
    assert request.sources == ["switch"]


def test_switch_jobs_render_as_direct_company_imports() -> None:
    parser = SwitchJobsParser()
    job = parser.normalize_job(
        {
            "id": "557",
            "title": "Technical Documentation Specialist (60%) in Zürich",
            "url": "https://recruitingapp-2563.umantis.com/Vacancies/557/Description/1",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="switch-557",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Switch import"
    assert stored["id"] == "switch-557"
