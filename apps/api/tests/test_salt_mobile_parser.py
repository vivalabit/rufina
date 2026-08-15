from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.salt_mobile import (
    PAGE_PARAMETER,
    SaltMobileJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://company.jobcloud.ch/de/job-list/1772460841133x163767963229093900?embedded=yes"
LIST_PATH = "/de/job-list/1772460841133x163767963229093900"
JOB_IDS = (
    "b6bb546f-f060-4a80-98bb-cc5d31f82a54",
    "449c7e97-b243-4a29-aa09-b7eb0761bad4",
    "711b67be-b54f-4e03-968e-c0ba36c2857a",
    "d0f4467c-cec1-4cbf-8021-9775cb51391e",
    "a5f78b8e-6785-4149-9cf2-54922f1d8303",
)
TITLES = (
    "Customer Onboarding & Migration Specialist",
    "Customer Care Advisor (DE/FR)",
    "Salt Store Vendeur/se - Verkäufer/in Bienne/Biel 80%-100%",
    "Dialogatori/trici 100% – Vendita Diretta POS Mobile Sud",
    "Salt Store Verkäufer-/Verkäuferin Aargau 100%",
)


def listing_html(indexes: list[int], *, page: int, total_pages: int = 3) -> str:
    alternate = f"https://company.jobcloud.ch{LIST_PATH}"
    if page > 1:
        alternate = f"{alternate}?{PAGE_PARAMETER}={page}"
    items = "".join(
        f"""
        <div role="listitem" class="job_list_item w-dyn-item">
          <a class="job_list_item-link" href="/de/jobs/{JOB_IDS[index]}">
            <div fs-cmsfilter-field="JobCategory">Informatik / Telekommunikation</div>
            <div fs-cmsfilter-field="name">{TITLES[index]}</div>
            <div fs-cmsfilter-field="Location">Bern, Freiburg, Solothurn</div>
            <div fs-cmsfilter-field="Pensum">{"100%" if index != 2 else "80 - 100%"}</div>
            <div fs-cmsfilter-field="ContractType">Festanstellung</div>
          </a>
        </div>
        """
        for index in indexes
    )
    return f"""
    <html lang="de-CH" data-wf-item-slug="1772460841133x163767963229093900">
      <head>
        <title>Salt Mobile SA -</title>
        <link rel="alternate" hreflang="de-CH" href="{alternate}">
      </head><body>
        <div class="job_list_list">{items}</div>
        <div class="w-page-count">{page} / {total_pages}</div>
      </body>
    </html>
    """


def detail_html(index: int) -> str:
    job_id = JOB_IDS[index]
    title = TITLES[index]
    detail_url = f"https://company.jobcloud.ch/de/jobs/{job_id}"
    workload = "80 - 100%" if index == 2 else "100%"
    return f"""
    <html lang="de-CH" data-wf-item-slug="{job_id}"><head>
      <link rel="alternate" hreflang="de-CH" href="{detail_url}">
      <meta property="og:title" content="Jetzt bewerben! - {title} bei Salt Mobile SA">
    </head><body>
      <h1>{title}</h1>
      <div class="text-rich-text w-richtext">
        <p>Wir suchen talentierte Mitarbeitende.</p>
        <p><strong>Pensum</strong>: {workload}</p>
        <p><strong>Vertragsart</strong>: Festanstellung</p>
        <p><strong>Arbeitsort</strong>: Biel/Bienne</p>
        <h2>Deine Aufgaben</h2>
        <ul><li>Kundenprojekte koordinieren</li><li>Technische Lösungen betreuen</li></ul>
      </div>
      <a id="job-ad-apply-btn" href="https://www.jobup.ch/fr/application/create/{job_id}?utm_source=relationship">Bewerben</a>
      <div class="job_details_keyinfo-details"><div class="text-weight-semibold">Veröffentlicht</div><div class="text-size-small">13.8.2026</div></div>
      <div class="job_details_keyinfo-details"><div class="text-weight-semibold">Pensum</div><div class="text-size-small">{workload}</div></div>
      <div class="job_details_keyinfo-details"><div class="text-weight-semibold">Vertrag</div><div class="text-size-small">Festanstellung</div></div>
      <div class="job_details_keyinfo-details"><div class="text-weight-semibold">Arbeitsort</div><div class="text-size-small">, Bern, Freiburg, Solothurn</div></div>
    </body></html>
    """


def test_salt_mobile_collects_every_webflow_page_and_enriches_details() -> None:
    requests: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == LIST_PATH:
            page = int(request.url.params.get(PAGE_PARAMETER, "1"))
            requests.append(("listing", page))
            indexes = [0, 1] if page == 1 else [2, 3] if page == 2 else [4]
            return httpx.Response(
                200,
                text=listing_html(indexes, page=page),
                request=request,
            )
        job_id = request.url.path.rsplit("/", 1)[-1]
        index = JOB_IDS.index(job_id)
        requests.append(("detail", index))
        return httpx.Response(200, text=detail_html(index), request=request)

    result = SaltMobileJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requests == [
        ("listing", 1),
        ("listing", 2),
        ("listing", 3),
        ("detail", 0),
        ("detail", 1),
        ("detail", 2),
        ("detail", 3),
        ("detail", 4),
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 5 Salt Mobile vacancies across 3 Webflow pages using 3 requests"
    )
    assert len(result.jobs) == 5
    assert all(job.description for job in result.jobs)

    job = result.jobs[0]
    assert job.source == "salt_mobile"
    assert job.title == TITLES[0]
    assert job.company == "Salt Mobile SA"
    assert job.location == "Biel/Bienne"
    assert job.url == f"https://company.jobcloud.ch/de/jobs/{JOB_IDS[0]}"
    assert job.apply_url == f"https://www.jobup.ch/fr/application/create/{JOB_IDS[0]}"
    assert job.posted_at == "2026-08-13"
    assert job.employment_type == "Permanent · 100%"
    assert job.description == (
        "Wir suchen talentierte Mitarbeitende.\n\n"
        "Pensum: 100%\n\n"
        "Vertragsart: Festanstellung\n\n"
        "Arbeitsort: Biel/Bienne\n\n"
        "Deine Aufgaben\n\n"
        "- Kundenprojekte koordinieren\n"
        "- Technische Lösungen betreuen"
    )
    assert job.raw["listing_page"] == 1
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 5


def test_salt_mobile_preserves_listing_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == LIST_PATH:
            return httpx.Response(
                200,
                text=listing_html([0], page=1, total_pages=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        SaltMobileJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == TITLES[0]
    assert job.location == "Bern, Freiburg, Solothurn"
    assert job.employment_type == "Permanent · 100%"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "page_html, message",
    [
        ("<html></html>", "unexpected identity"),
        (
            listing_html([0], page=1, total_pages=1).replace("1 / 1", "1 / 0"),
            "invalid page count",
        ),
        (
            listing_html([0, 0], page=1, total_pages=1),
            "duplicate vacancy IDs",
        ),
    ],
)
def test_salt_mobile_rejects_invalid_catalog(page_html: str, message: str) -> None:
    parser = SaltMobileJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page_html, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_salt_mobile_max_pages_prevents_silent_catalog_truncation() -> None:
    parser = SaltMobileJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([0, 1], page=1, total_pages=2),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="limit of 1 pages"):
        parser.search(LinkedInSearchRequest())


def test_salt_mobile_wraps_request_failures() -> None:
    parser = SaltMobileJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_salt_mobile_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["salt_mobile"]
    assert isinstance(parser, SaltMobileJobsParser)
    assert parser.base_url == settings.salt_mobile_jobs_base_url
    assert parser.max_pages == settings.salt_mobile_jobs_max_pages
    assert parser.max_catalog_passes == settings.salt_mobile_jobs_max_catalog_passes
    assert parser.detail_workers == settings.salt_mobile_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Salt Mobile", "filters": {}},
            "sources": ["salt_mobile", "salt_mobile"],
        }
    )
    assert request.sources == ["salt_mobile"]


def test_salt_mobile_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": JOB_IDS[0],
        "title": TITLES[0],
        "location": "Biel/Bienne",
        "workload": "100%",
        "contract": "Festanstellung",
        "url": f"https://company.jobcloud.ch/de/jobs/{JOB_IDS[0]}",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id=f"salt_mobile-{JOB_IDS[0]}",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == f"salt_mobile-{JOB_IDS[0]}"
    assert stored["logo"] == "company"
    assert stored["department"] == "Salt Mobile SA import"
    assert stored["company"] == "Salt Mobile SA"
