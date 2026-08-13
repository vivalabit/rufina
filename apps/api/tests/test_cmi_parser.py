from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.cmi import CmiJobsParser, normalize_job, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://cmi.test/karriere/"
DETAIL_CANONICAL = "https://cmi.ch/karriere/stellen/"
JOB_ONE = "808dbb0a-dde0-d52b-001d-3dcc84d46f46"
JOB_TWO = "25eac6de-1a70-5557-5343-4becc30fec76"
APPLY_ONE = (
    "https://cmi.jobportal.abaservices.ch/application-process/"
    "35ddfa55-c2bf-48d5-b8dd-512c140b6841/"
    "c01dcc7f-798c-82b6-a4e3-7ee4365877f6?jp=ABACUS"
)


def page_head(canonical: str, *, site_name: str = "CM Informatik AG") -> str:
    return f"""
    <head>
      <meta property="og:site_name" content="{site_name}">
      <link rel="canonical" href="{canonical}">
    </head>
    """


def listing_card(*, item_id: str, job_id: str, title: str) -> str:
    return f"""
    <div class="jet-listing-grid__item" data-post-id="{item_id}">
      <div class="job-box">
        <h3 class="elementor-heading-title">{title}</h3>
        <a class="jet-listing-dynamic-link__link"
           href="https://cmi.test/karriere/stellen/?item_id={item_id}&amp;JobId={job_id}">
          Mehr erfahren
        </a>
      </div>
    </div>
    """


def listing_html(
    cards: list[str],
    *,
    pages: str = "1",
    site_name: str = "CM Informatik AG",
) -> str:
    return f"""
    <html lang="de">
      {page_head(BASE_URL, site_name=site_name)}
      <body>
        <div class="jet-listing-grid__items" data-listing-id="40076"
             data-listing-source="query" data-query-id="12" data-pages="{pages}">
          {''.join(cards[:1])}
          <div class="jet-listing-grid__item empty"></div>
        </div>
        <div class="jet-listing-grid__items" data-listing-id="40306"
             data-listing-source="rest_api_endpoint" data-query-id="" data-pages="1">
          {''.join(cards[1:])}
          <div class="jet-listing-grid__item empty"></div>
        </div>
      </body>
    </html>
    """


def detail_record(
    *,
    item_id: str,
    title: str,
    apply_url: str = APPLY_ONE,
    description: str = "Du entwickelst digitale Lösungen in einem Pensum von 80 - 100 %.",
) -> str:
    return f"""
    <div class="jet-listing-grid__item" data-post-id="{item_id}">
      <div class="rest-post">
        <div class="intro-text"><div class="elementor-widget-container">
          <p><strong>Willst du etwas bewegen?</strong></p>
        </div></div>
        <h1 class="elementor-heading-title">{title}</h1>
        <div class="rest-import"><div class="elementor-widget-container">
          &lt;p&gt;{description}&lt;/p&gt;
        </div></div>
        <div class="rest-import-list"><div class="elementor-widget-container">
          &lt;ul&gt;&lt;li&gt;Du arbeitest im Scrum Team.&lt;/li&gt;&lt;/ul&gt;
        </div></div>
        <a class="bdt-ep-button" href="{apply_url}">Jetzt bewerben</a>
      </div>
    </div>
    """


def detail_html(*records: str) -> str:
    return f"""
    <html lang="de">
      {page_head(DETAIL_CANONICAL)}
      <body>
        <div class="jet-listing-grid__items" data-query-id="12" data-pages="1">
          {''.join(records)}
        </div>
      </body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            item_id="12-1",
            job_id=JOB_ONE,
            title="Lead Scrum Team und Softwareentwickler:in",
        ),
        listing_card(
            item_id="12-2",
            job_id=JOB_TWO,
            title="Applikationsbetreuer:in öffentliche Verwaltung",
        ),
    ]


def test_cmi_collects_complete_catalog_and_selects_matching_detail_record() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/karriere/":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        return httpx.Response(
            200,
            text=detail_html(
                detail_record(
                    item_id="12-1",
                    title="Lead Scrum Team und Softwareentwickler:in",
                ),
                detail_record(
                    item_id="12-2",
                    title="Applikationsbetreuer:in öffentliche Verwaltung",
                    description="Du betreust die CMI Lösungsplattform.",
                ),
            ),
            request=request,
        )

    result = CmiJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 3
    assert calls[1].endswith(f"item_id=12-1&JobId={JOB_ONE}&nocache=1")
    assert calls[2].endswith(f"item_id=12-2&JobId={JOB_TWO}&nocache=1")
    assert result.status == "completed"
    assert result.message == "Scanned 2 CMI Switzerland vacancies from the official catalog"
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "cmi"
    assert first.title == "Lead Scrum Team und Softwareentwickler:in"
    assert first.company == "CM Informatik AG"
    assert first.location == "Schwerzenbach, Switzerland"
    assert first.url == (
        f"https://cmi.test/karriere/stellen/?item_id=12-1&JobId={JOB_ONE}"
    )
    assert first.apply_url == APPLY_ONE
    assert first.posted_at is None
    assert first.employment_type == "80–100%"
    assert first.description and "Du arbeitest im Scrum Team" in first.description
    assert first.raw["item_id"] == "12-1"
    assert result.jobs[1].description and "Du betreust die CMI" in result.jobs[1].description


def test_cmi_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/":
            return httpx.Response(200, text=listing_html([catalog_fixture()[0]]), request=request)
        return httpx.Response(503, request=request)

    job = (
        CmiJobsParser(base_url=BASE_URL, transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Lead Scrum Team und Softwareentwickler:in"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_cmi_rejects_incomplete_paginated_or_duplicate_catalog() -> None:
    card = catalog_fixture()[0]

    def run(cards: list[str], *, pages: str = "1") -> None:
        CmiJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(cards, pages=pages),
                    request=request,
                )
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="complete vacancy catalog"):
        run([card], pages="2")
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        run([card, card])
    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        run([])


def test_cmi_rejects_wrong_identity_and_untrusted_apply_url() -> None:
    parser = CmiJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), site_name="Other AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    detail_url = f"{BASE_URL}stellen/?item_id=12-1&JobId={JOB_ONE}"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                detail_record(
                    item_id="12-1",
                    title="Lead Scrum Team und Softwareentwickler:in",
                    apply_url="https://attacker.example/apply",
                )
            ),
            page_url=f"{detail_url}&nocache=1",
            expected_url=detail_url,
            expected_item_id="12-1",
            expected_job_id=JOB_ONE,
            expected_title="Lead Scrum Team und Softwareentwickler:in",
        )


def test_cmi_wraps_listing_request_failures() -> None:
    parser = CmiJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_cmi_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["cmi"]
    assert isinstance(parser, CmiJobsParser)
    assert parser.base_url == settings.cmi_jobs_base_url
    assert parser.detail_workers == settings.cmi_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {"config": {"name": "CMI", "filters": {}}, "sources": ["cmi", "cmi"]}
    )
    assert request.sources == ["cmi"]


def test_cmi_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": JOB_ONE,
            "item_id": "12-1",
            "title": "Lead Scrum Team und Softwareentwickler:in",
            "url": f"https://cmi.ch/karriere/stellen/?item_id=12-1&JobId={JOB_ONE}",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"cmi-{JOB_ONE}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "CM Informatik AG import"
    assert stored["id"] == f"cmi-{JOB_ONE}"
