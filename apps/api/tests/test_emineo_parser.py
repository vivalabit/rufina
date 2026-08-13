from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.emineo import EmineoJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://emineo.test/en/career/open-positions/"
EXPORT_URL = "https://recruitingapp-2895.umantis.com/XMLExport/136"


def listing_card(
    job_id: str,
    *,
    title: str,
    location: str,
    date: str,
    category: str,
    summary: str,
) -> str:
    return f"""
    <div class="single-job-col-4">
      <div class="job-category">_{category}</div>
      <div class="job-online-from">Online since: {date}</div>
      <h3 class="job-title">{title}</h3>
      <div class="job-location">{location}</div>
      <div class="job-description">{summary}</div>
      <a class="btn-link" href="{BASE_URL}job-description/{job_id}">Read more</a>
    </div>
    """


def listing_html(cards: list[str], *, site_name: str = "emineo") -> str:
    return f"""
    <html lang="en-US">
      <head>
        <link rel="canonical" href="{BASE_URL}">
        <meta property="og:site_name" content="{site_name}">
      </head>
      <body>
        <style data-test="{EXPORT_URL}"></style>
        <div class="jobs-list-main-container">{"".join(cards)}</div>
      </body>
    </html>
    """


def export_record(
    job_id: str,
    *,
    title: str,
    location: str,
    date: str,
    category: str,
    summary: str,
    apply_host: str = "recruitingapp-2895.umantis.com",
) -> str:
    return f"""
      <PosID>{job_id}</PosID>
      <LastModified>{date}</LastModified>
      <Ausschreibungstext>
        <Stellentitel><![CDATA[{title}]]></Stellentitel>
        <TitelAufgaben>Your responsibilities:</TitelAufgaben>
        <TextAufgaben><![CDATA[<ul><li>Deliver modern SAP projects.</li></ul>]]></TextAufgaben>
        <TitelAnforderungen>Your qualifications:</TitelAnforderungen>
        <TextAnforderungen><![CDATA[<p>Strong consulting experience.</p>]]></TextAnforderungen>
        <TitelWirbieten>You can look forward to:</TitelWirbieten>
        <TextWirbieten><![CDATA[<ul><li>Flexible working hours.</li></ul>]]></TextWirbieten>
        <Kurzbeschreibung><![CDATA[{summary}]]></Kurzbeschreibung>
      </Ausschreibungstext>
      <Suchkriterien>
        <Beschäftigungsart>permanent contract</Beschäftigungsart>
        <EinstiegAls>Senior</EinstiegAls>
        <Unternehmensbereich>{category}</Unternehmensbereich>
        <Arbeitsort>{location}</Arbeitsort>
      </Suchkriterien>
      <Apply_url>https://{apply_host}/Vacancies/{job_id}/Application/CheckLogin/2?lang=eng</Apply_url>
    """


def export_xml(records: list[str]) -> str:
    return f"<?xml version='1.0'?><Jobs><vacancies>{''.join(records)}</vacancies></Jobs>"


def catalog_fixture() -> tuple[list[str], list[str]]:
    jobs = [
        {
            "id": "389",
            "title": "SAP Accounts Receivable Project Manager (m/f/d), 80–100%",
            "location": "Baar, Zürich, Lausanne",
            "date": "10.07.2026 CET",
            "category": "SAP Consulting",
            "summary": "Deliver SAP collections projects and advise clients.",
        },
        {
            "id": "397",
            "title": "Senior Consultant SAP S/4HANA Finance (w/m/d), 80-100% - Lausanne",
            "location": "Lausanne",
            "date": "12.08.2026 CET",
            "category": "SAP Consulting",
            "summary": "Support customers throughout their SAP S/4HANA journey.",
        },
    ]
    return (
        [listing_card(job.pop("id"), **job) for job in [dict(item) for item in jobs]],
        [export_record(job.pop("id"), **job) for job in [dict(item) for item in jobs]],
    )


def test_emineo_reconciles_complete_html_and_xml_catalogs() -> None:
    cards, records = catalog_fixture()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        text = listing_html(cards) if request.url.host == "emineo.test" else export_xml(records)
        return httpx.Response(200, text=text, request=request)

    result = EmineoJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == ["/en/career/open-positions/", "/XMLExport/136"]
    assert result.message == "Scanned 2 emineo Switzerland vacancies from the official catalog"
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "emineo"
    assert first.company == "emineo AG"
    assert first.location == "Baar / Zürich / Lausanne, Switzerland"
    assert first.url == f"{BASE_URL}job-description/389"
    assert first.apply_url == (
        "https://recruitingapp-2895.umantis.com/Vacancies/389/Application/CheckLogin/2?lang=eng"
    )
    assert first.posted_at == "2026-07-10"
    assert first.employment_type == "80–100%"
    assert first.seniority == "Senior"
    assert first.description and "- Deliver modern SAP projects" in first.description
    assert result.jobs[1].location == "Lausanne, Switzerland"


def test_emineo_rejects_catalog_mismatch() -> None:
    cards, records = catalog_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        text = listing_html(cards[:1]) if request.url.host == "emineo.test" else export_xml(records)
        return httpx.Response(200, text=text, request=request)

    with pytest.raises(DirectCompanyRequestError, match="catalogs do not match"):
        EmineoJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())


def test_emineo_rejects_wrong_identity_or_duplicate_listing() -> None:
    cards, records = catalog_fixture()

    def run(page: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            text = page if request.url.host == "emineo.test" else export_xml(records)
            return httpx.Response(200, text=text, request=request)

        EmineoJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        run(listing_html(cards, site_name="Attacker AG"))
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        run(listing_html([cards[0], cards[0]]))


def test_emineo_rejects_untrusted_apply_url() -> None:
    cards, records = catalog_fixture()
    records[0] = records[0].replace(
        "recruitingapp-2895.umantis.com",
        "attacker.example",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        text = listing_html(cards) if request.url.host == "emineo.test" else export_xml(records)
        return httpx.Response(200, text=text, request=request)

    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        EmineoJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())


def test_emineo_wraps_request_failures() -> None:
    parser = EmineoJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_emineo_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["emineo"]
    assert isinstance(parser, EmineoJobsParser)
    assert parser.base_url == settings.emineo_jobs_base_url
    assert parser.export_url == settings.emineo_jobs_export_url

    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "emineo", "filters": {}}, "sources": ["emineo", "emineo"]}
    )
    assert request.sources == ["emineo"]


def test_emineo_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": "389",
            "title": "SAP Accounts Receivable Project Manager (m/f/d), 80–100%",
            "location": "Baar / Zürich / Lausanne, Switzerland",
            "url": f"{BASE_URL}job-description/389",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="emineo-389",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "emineo AG import"
    assert stored["id"] == "emineo-389"
