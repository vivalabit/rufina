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
from app.services.parsers.companies.zuercher_kantonalbank import (
    ZuercherKantonalbankJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_row(
    *,
    job_id: str,
    publication_id: str,
    title: str,
    location: str,
    workload: str,
    target_group: str,
) -> str:
    return f"""
    <tr>
      <td class="position">
        <a href="/792841/{job_id}/pub/{publication_id}">{title}</a>
      </td>
      <td class="operationArea">IT / Business Engineering</td>
      <td class="workplace">{location}</td>
      <td class="workload">{workload}</td>
      <td class="segment">{target_group}</td>
      <td class="locale">de</td>
    </tr>
    """


def listing_html() -> str:
    rows = "".join(
        [
            listing_row(
                job_id="11001",
                publication_id="1",
                title="DevOps Engineer SAP PaPM (m/w/d)",
                location="Zürich",
                workload="80% - 100%",
                target_group="Berufserfahrene",
            ),
            listing_row(
                job_id="11077",
                publication_id="5",
                title="Software Engineer in Asset Management (m/w/d)",
                location="Zürich",
                workload="100%",
                target_group="Berufseinsteiger:in, Berufserfahrene",
            ),
        ]
    )
    return f"""
    <html><body>
      <table class="jquery-tablesorter searchResult">
        <thead><tr>
          <th class="position jquery-tablesorter-th">Stelle</th>
          <th class="operationArea jquery-tablesorter-th">Funktion</th>
          <th class="workplace jquery-tablesorter-th">Arbeitsort</th>
          <th class="workload jquery-tablesorter-th">Pensum</th>
          <th class="segment jquery-tablesorter-th">Zielgruppe</th>
          <th class="locale jquery-tablesorter-th">Sprache</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """


def detail_html(*, job_id: str, title: str) -> str:
    schema = {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (
            f"<h1>{title}</h1>"
            "<h2>80% - 100% | IT / Business Engineering | Zürich | Berufserfahrene</h2>"
            "<div>Build dependable banking platforms.</div><br />"
            "<div>Deine Aufgaben</div><br />"
            "<div><ul><li>Own production services.</li>"
            "<li>Support delivery teams.</li></ul></div>"
        ),
        "datePosted": "2026-02-02T10:42:27.649455+00:00",
        "validThrough": "2026-09-30",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Zürcher Kantonalbank und ihre Tochtergesellschaften",
        },
        "employmentType": ["FULL_TIME"],
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "CH",
                "addressLocality": "Zürich",
                "addressRegion": "ZH",
            },
        },
    }
    return f"""
    <html><head>
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <a class="applyLink" href="/792841/{job_id}/index.html?cid=1&amp;lang=de">
        Jetzt online bewerben
      </a>
    </body></html>
    """


def test_zuercher_kantonalbank_scans_and_enriches_full_catalog() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/792841/search.html":
            return httpx.Response(200, text=listing_html())
        job_id = request.url.path.split("/")[2]
        title = (
            "DevOps Engineer SAP PaPM (m/w/d)"
            if job_id == "11001"
            else "Software Engineer in Asset Management (m/w/d)"
        )
        return httpx.Response(200, text=detail_html(job_id=job_id, title=title))

    parser = ZuercherKantonalbankJobsParser(
        base_url="https://apply.refline.test/792841/search.html",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == "Scanned 2 Zürcher Kantonalbank vacancies from one page"
    assert len(requests) == 3
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "zuercher_kantonalbank"
    assert first.title == "DevOps Engineer SAP PaPM (m/w/d)"
    assert first.company == "Zürcher Kantonalbank"
    assert first.location == "Zürich"
    assert first.url == "https://apply.refline.test/792841/11001/pub/1"
    assert first.apply_url == ("https://apply.refline.test/792841/11001/index.html?cid=1&lang=de")
    assert first.posted_at == "2026-02-02T10:42:27.649455+00:00"
    assert first.employment_type == "80% - 100%"
    assert first.seniority == "Berufserfahrene"
    assert first.description == (
        "Build dependable banking platforms.\n\n"
        "Deine Aufgaben\n\n"
        "- Own production services.\n"
        "- Support delivery teams."
    )
    assert first.raw["id"] == "11001"
    assert first.raw["publication_id"] == "1"
    assert first.raw["operation_area"] == "IT / Business Engineering"
    assert first.raw["language"] == "de"
    assert first.raw["detail"]["valid_through"] == "2026-09-30"


def test_zuercher_kantonalbank_preserves_listing_when_detail_fails() -> None:
    one_row_listing = listing_html().replace(
        listing_row(
            job_id="11077",
            publication_id="5",
            title="Software Engineer in Asset Management (m/w/d)",
            location="Zürich",
            workload="100%",
            target_group="Berufseinsteiger:in, Berufserfahrene",
        ),
        "",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/792841/search.html":
            return httpx.Response(200, text=one_row_listing)
        return httpx.Response(503, text="temporarily unavailable")

    parser = ZuercherKantonalbankJobsParser(
        base_url="https://apply.refline.test/792841/search.html",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "DevOps Engineer SAP PaPM (m/w/d)"
    assert job.location == "Zürich"
    assert job.posted_at is None
    assert job.description is None
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_zuercher_kantonalbank_rejects_listing_without_table_contract() -> None:
    parser = ZuercherKantonalbankJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Offene Stellen</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy table"):
        parser.search(LinkedInSearchRequest())


def test_zuercher_kantonalbank_rejects_duplicate_vacancy_ids() -> None:
    duplicate = listing_html().replace("/792841/11077/pub/5", "/792841/11001/pub/5")
    parser = ZuercherKantonalbankJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=duplicate))
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_zuercher_kantonalbank_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["zuercher_kantonalbank"]
    assert isinstance(parser, ZuercherKantonalbankJobsParser)
    assert parser.base_url == settings.zuercher_kantonalbank_jobs_base_url
    assert parser.detail_workers == settings.zuercher_kantonalbank_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Zürcher Kantonalbank", "filters": {}},
            "sources": ["zuercher_kantonalbank", "zuercher_kantonalbank"],
        }
    )
    assert request.sources == ["zuercher_kantonalbank"]


def test_zuercher_kantonalbank_jobs_render_as_direct_company_imports() -> None:
    parser = ZuercherKantonalbankJobsParser()
    job = parser.normalize_job(
        {
            "id": "11001",
            "publication_id": "1",
            "title": "DevOps Engineer SAP PaPM (m/w/d)",
            "location": "Zürich",
            "workload": "80% - 100%",
            "target_group": "Berufserfahrene",
            "url": "https://apply.refline.ch/792841/11001/pub/1",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="zuercher_kantonalbank-11001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Zürcher Kantonalbank import"
    assert stored["id"] == "zuercher_kantonalbank-11001"
