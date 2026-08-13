from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bsi_software import (
    BsiSoftwareJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.bsi-software.com/en/career/jobs"
JOBS_URL = "https://www.bsi-software.com/de/karriere/jobs"
API_URL = "https://www.bsi-software.com/api/jobs"


def catalog_record(
    slug: str,
    *,
    title: str,
    workload: str,
    tags: list[str],
) -> dict[str, object]:
    return {
        "metadata": {"_type": "studio.WebsiteContentTypeMetadata"},
        "metadataLocale": {"_type": "studio.WebsiteContentTypeMetadata"},
        "tags": tags,
        "text": workload,
        "title": title,
        "url": f"karriere/jobs/{slug}",
    }


def catalog_fixture() -> list[dict[str, object]]:
    return [
        catalog_record(
            "software-engineer",
            title="Software Engineer (all genders)",
            workload="80 - 100 %",
            tags=["junior", "baar", "baden", "bern", "zürich"],
        ),
        catalog_record(
            "lehre-informatiker-Plattformentwicklung_1",
            title="Lehre als InformatikerIn EFZ Fachrichtung Plattformentwicklung",
            workload="100 %",
            tags=["lehre", "baden"],
        ),
        catalog_record(
            "software-engineer-de",
            title="Software Engineer Germany (all genders)",
            workload="100 %",
            tags=["junior", "darmstadt", "hamburg"],
        ),
    ]


def detail_html(
    slug: str,
    *,
    title: str,
    tags: list[str],
    apply_host: str = "services.bsi-software.com",
) -> str:
    page_url = f"{JOBS_URL}/{slug}"
    position = title.split(" (", 1)[0].replace(" ", "%20")
    return f"""
    <html lang="de">
      <head>
        <meta property="og:title" content="{title}">
        <meta name="x-tags" content="{";".join(tags)};">
        <meta name="x-create-date" content="05.05.2026 10:59:54">
        <link rel="canonical" href="{page_url}">
      </head>
      <body>
        <div class="flex-grow-1">
          <h2>Deine Aufgaben</h2>
          <ul><li>Du entwickelst nachhaltige Softwarelösungen.</li></ul>
          <h2>Wir suchen Macher</h2>
          <p>Du bringst Erfahrung in der Softwareentwicklung mit.</p>
          <a href="https://{apply_host}/studio/public/e/l/jobs?lang=de&amp;position={position}&amp;id=2595876">
            Jetzt bewerben
          </a>
        </div>
      </body>
    </html>
    """


def test_bsi_software_collects_complete_catalog_and_enriches_swiss_jobs() -> None:
    records = catalog_fixture()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/jobs":
            assert request.url.params["lang"] == "de"
            assert request.url.params["tags"] == "[]"
            return httpx.Response(
                200,
                json={"items": records, "totalItemCount": len(records)},
                request=request,
            )
        record = next(
            item
            for item in records
            if str(item["url"]).endswith(request.url.path.rsplit("/", 1)[-1])
        )
        return httpx.Response(
            200,
            text=detail_html(
                request.url.path.rsplit("/", 1)[-1],
                title=str(record["title"]),
                tags=list(record["tags"]),  # type: ignore[arg-type]
            ),
            request=request,
        )

    result = BsiSoftwareJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/api/jobs",
        "/de/karriere/jobs/software-engineer",
        "/de/karriere/jobs/lehre-informatiker-Plattformentwicklung_1",
    ]
    assert result.status == "completed"
    assert result.search_url == BASE_URL
    assert result.message == (
        "Scanned 2 BSI Software Switzerland vacancies from 3 official catalog records"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "bsi_software"
    assert first.title == "Software Engineer (all genders)"
    assert first.company == "BSI Software"
    assert first.location == "Baar / Baden / Bern / Zürich, Switzerland"
    assert first.url == f"{JOBS_URL}/software-engineer"
    assert first.apply_url == (
        "https://services.bsi-software.com/studio/public/e/l/jobs?"
        "lang=de&position=Software%20Engineer&id=2595876"
    )
    assert first.posted_at == "2026-05-05"
    assert first.employment_type == "80–100%"
    assert first.description and "Deine Aufgaben" in first.description
    assert first.description and "- Du entwickelst" in first.description
    assert first.raw["locations"] == ["Baar", "Baden", "Bern", "Zürich"]
    assert result.jobs[1].employment_type == "100%"


def test_bsi_software_paginates_and_rejects_incomplete_catalog() -> None:
    record = catalog_fixture()[0]

    def stalled_handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(
                200,
                json={"items": [record], "totalItemCount": 2},
                request=request,
            )
            if request.url.params["startIndex"] == "0"
            else httpx.Response(
                200,
                json={"items": [], "totalItemCount": 2},
                request=request,
            )
        )

    parser = BsiSoftwareJobsParser(transport=httpx.MockTransport(stalled_handler))
    with pytest.raises(DirectCompanyRequestError, match="pagination stalled"):
        parser.search(LinkedInSearchRequest())


def test_bsi_software_rejects_duplicate_or_invalid_catalog_records() -> None:
    record = catalog_fixture()[0]

    def run(records: list[dict[str, object]]) -> None:
        parser = BsiSoftwareJobsParser(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"items": records, "totalItemCount": len(records)},
                    request=request,
                )
            )
        )
        parser.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        run([record, record])
    invalid = dict(record)
    invalid["url"] = "https://attacker.example/vacancy"
    with pytest.raises(DirectCompanyRequestError, match="incomplete record"):
        run([invalid])


def test_bsi_software_preserves_listing_when_detail_fails() -> None:
    record = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/jobs":
            return httpx.Response(
                200,
                json={"items": [record], "totalItemCount": 1},
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        BsiSoftwareJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Software Engineer (all genders)"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_bsi_software_rejects_wrong_detail_identity_or_apply_host() -> None:
    slug = "software-engineer"
    title = "Software Engineer (all genders)"
    tags = ["junior", "baar", "baden", "bern", "zürich"]
    page_url = f"{JOBS_URL}/{slug}"

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(slug, title=title, tags=tags, apply_host="attacker.example"),
            page_url=page_url,
            expected_url=page_url,
            expected_slug=slug,
            expected_title=title,
            expected_tags=tags,
        )


def test_bsi_software_wraps_catalog_request_failures() -> None:
    parser = BsiSoftwareJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bsi_software_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bsi_software"]
    assert isinstance(parser, BsiSoftwareJobsParser)
    assert parser.base_url == settings.bsi_software_jobs_base_url
    assert parser.api_url == settings.bsi_software_jobs_api_url
    assert parser.max_pages == settings.bsi_software_jobs_max_pages
    assert parser.detail_workers == settings.bsi_software_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "BSI Software", "filters": {}},
            "sources": ["bsi_software", "bsi_software"],
        }
    )
    assert request.sources == ["bsi_software"]


def test_bsi_software_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": "software-engineer",
            "title": "Software Engineer (all genders)",
            "location": "Baar / Baden / Bern / Zürich, Switzerland",
            "url": f"{JOBS_URL}/software-engineer",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="bsi_software-software-engineer",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "BSI Software import"
    assert stored["id"] == "bsi_software-software-engineer"
