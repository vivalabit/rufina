from __future__ import annotations

import html
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.boss_info import (
    BOSS_INFO_JOBS_URL,
    BossInfoJobsParser,
    canonical_application_url,
    normalize_job,
    normalize_workload,
)
from app.services.vacancy_search import create_vacancy_search_runner

RECORDS = [
    {
        "slug": "projektleiter-bosserp-60-100",
        "title": "Projektleiter bossERP 60–100%",
        "application_id": "JOB-1166",
        "workload": "60–100%",
    },
    {
        "slug": "sales-manager-ict-100",
        "title": "Sales Manager ICT 100%",
        "application_id": "JOB-1171",
        "workload": "100%",
    },
]


def schema_html(*, url: str, name: str, published_at: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "url": url,
                "name": name,
                "datePublished": published_at,
            },
            {"@type": "Organization", "name": "Boss Info"},
        ],
    }
    return (
        '<script type="application/ld+json" class="yoast-schema-graph">'
        f"{json.dumps(payload)}"
        "</script>"
    )


def listing_html(
    records: list[dict[str, str]] = RECORDS,
    *,
    page_title: str = "Offene Stellen bei Boss Info - Jobs im Bereich ICT und IT",
) -> str:
    cards = "".join(
        (
            f'<div class="job category-{index}">'
            f"<h3>{html.escape(record['title'])}</h3>"
            f'<a class="full" href="https://www.bossinfo.com/jobs/{record["slug"]}/">'
            f"Details zum Job {html.escape(record['title'])}</a>"
            "</div>"
        )
        for index, record in enumerate(records)
    )
    return f"""
    <html lang="de-DE"><head>
      <title>{page_title}</title>
      <link rel="canonical" href="{BOSS_INFO_JOBS_URL}">
      <meta property="og:site_name" content="Boss Info">
      {schema_html(url=BOSS_INFO_JOBS_URL, name=page_title, published_at="2026-02-05T10:28:19+00:00")}
    </head><body><main>
      <div id="jobs">
        <h2>Offene Stellen</h2>
        <p>Entdecke unsere aktuellen Stellenangebote.</p>
        <div class="wpb_jobs_column"><div class="jobs">{cards}</div></div>
      </div>
    </main></body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    visible_title: str | None = None,
    apply_host: str = "forms.swisshrmonline.ch",
) -> str:
    url = f"https://www.bossinfo.com/jobs/{record['slug']}/"
    title = visible_title or record["title"]
    apply_url = (
        f"https://{apply_host}/221313970241850?"
        f"xvna={record['slug']}&xvnu={record['application_id']}&xsou=%25mediaName%25"
    )
    return f"""
    <html lang="de-DE"><head>
      <title>Wir suchen {html.escape(title)} - Boss Info</title>
      <link rel="canonical" href="{url}">
      {schema_html(url=url, name=f"Wir suchen {title} - Boss Info", published_at="2026-07-21T11:17:24+00:00")}
    </head><body class="single single-jobs postid-123">
      <header><h1>{html.escape(title)}</h1></header>
      <main>
        <div id="job-kurzbeschreibung" class="vc_row">
          <p><strong>Pensum:</strong> {record["workload"]}</p>
          <p><strong>Arbeitsbeginn:</strong> Sofort oder nach Absprache</p>
          <p><strong>Berufserfahrung:</strong> Mehrjährige Erfahrung</p>
          <p><strong>Hauptarbeitsort:</strong> alle Standorte der Boss Info</p>
        </div>
        <div class="vc_row">
          <div class="wpb_content_element wpb_text_column"><div class="wpb_wrapper">
            <p>Du möchtest in einem innovativen Umfeld arbeiten und Kunden mit
            nachhaltigen digitalen Lösungen erfolgreich machen.</p>
          </div></div>
          <div class="wpb_content_element wpb_text_column"><div class="wpb_wrapper">
            <h4>Das sind deine Aufgaben</h4><ul>
              <li>Kunden kompetent beraten und langfristig begleiten</li>
              <li>Digitale Projekte eigenverantwortlich planen und leiten</li>
              <li>Anforderungen analysieren und passende Lösungen entwickeln</li>
            </ul>
          </div></div>
          <div class="wpb_content_element wpb_text_column"><div class="wpb_wrapper">
            <h4>Das bringst du mit</h4><ul>
              <li>Mehrjährige Berufserfahrung in einer vergleichbaren Rolle</li>
              <li>Ausgeprägte Kommunikations- und Beratungskompetenz</li>
              <li>Selbständige, zuverlässige und strukturierte Arbeitsweise</li>
            </ul>
          </div></div>
        </div>
        <a href="{apply_url}">Jetzt bewerben</a>
      </main>
    </body></html>
    """


def test_boss_info_collects_complete_catalog_and_enriches_details() -> None:
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/jobs/":
            return httpx.Response(200, text=listing_html())
        detail_requests.append(request.url.path)
        record = next(item for item in RECORDS if item["slug"] in request.url.path)
        return httpx.Response(200, text=detail_html(record))

    result = BossInfoJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert set(detail_requests) == {
        "/jobs/projektleiter-bosserp-60-100/",
        "/jobs/sales-manager-ict-100/",
    }
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Boss Info vacancies from the complete official careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "boss_info"
    assert first.title == "Projektleiter bossERP 60–100%"
    assert first.company == "Boss Info AG"
    assert first.location == "alle Standorte der Boss Info, Switzerland"
    assert first.url == "https://www.bossinfo.com/jobs/projektleiter-bosserp-60-100/"
    assert first.apply_url and "xvnu=JOB-1166" in first.apply_url
    assert first.posted_at == "2026-07-21T11:17:24+00:00"
    assert first.employment_type == "60–100%"
    assert first.description and "Das sind deine Aufgaben" in first.description
    assert "- Kunden kompetent beraten" in first.description
    assert first.raw["detail"]["application_id"] == "JOB-1166"
    assert first.raw["categories"] == ["category-0"]


def test_boss_info_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/jobs/":
            return httpx.Response(200, text=listing_html(RECORDS[:1]))
        return httpx.Response(503, text="unavailable")

    job = (
        BossInfoJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == RECORDS[0]["title"]
    assert job.location == "Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_boss_info_rejects_listing_identity_duplicates_and_catalog_limit() -> None:
    wrong_identity = BossInfoJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(page_title="Lookalike jobs"))
        )
    )
    duplicate = BossInfoJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([RECORDS[0], RECORDS[0]]))
        )
    )
    oversized = BossInfoJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html())),
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_boss_info_rejects_mismatched_detail_and_unsafe_application() -> None:
    scenarios = [
        detail_html(RECORDS[0], visible_title="Different vacancy"),
        detail_html(RECORDS[0], apply_host="evil.example"),
    ]

    for detail in scenarios:

        def handler(request: httpx.Request, detail_html_value: str = detail) -> httpx.Response:
            if request.url.path == "/karriere/jobs/":
                return httpx.Response(200, text=listing_html(RECORDS[:1]))
            return httpx.Response(200, text=detail_html_value)

        job = (
            BossInfoJobsParser(transport=httpx.MockTransport(handler))
            .search(LinkedInSearchRequest())
            .jobs[0]
        )
        assert job.description is None
        assert "detail_error" in job.raw


@pytest.mark.parametrize(
    ("value", "expected"),
    [("100%", "100%"), ("60-100 %", "60–100%"), ("0%", None), ("90–80%", None)],
)
def test_normalize_workload(value: str, expected: str | None) -> None:
    assert normalize_workload(value) == expected


def test_boss_info_accepts_only_official_swisshrm_application_urls() -> None:
    valid = (
        "https://forms.swisshrmonline.ch/221313970241850?"
        "xvna=Sales%20Manager&xvnu=JOB-1171&xsou=%25mediaName%25"
    )
    assert canonical_application_url(valid) == valid
    assert canonical_application_url(valid.replace("JOB-1171", "1171")) is None
    assert canonical_application_url(valid.replace("forms.swisshrmonline.ch", "evil.test")) is None


def test_boss_info_wraps_listing_request_failures() -> None:
    parser = BossInfoJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_boss_info_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["boss_info"]

    assert isinstance(parser, BossInfoJobsParser)
    assert parser.base_url == settings.boss_info_jobs_base_url
    assert parser.max_jobs == settings.boss_info_jobs_max_jobs
    assert parser.detail_workers == settings.boss_info_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Boss Info", "filters": {}},
            "sources": ["boss_info", "boss_info"],
        }
    )
    assert request.sources == ["boss_info"]

    record = {
        "id": RECORDS[0]["slug"],
        "title": RECORDS[0]["title"],
        "location": "Switzerland",
        "url": f"https://www.bossinfo.com/jobs/{RECORDS[0]['slug']}/",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="boss_info-JOB-1166",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Boss Info import"
    assert stored["company"] == "Boss Info AG"
