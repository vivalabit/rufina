from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.nexplore import (
    NEXPLORE_JOBS_API_URL,
    NexploreJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def catalog_record(
    job_id: str,
    *,
    slug: str,
    title: str,
    summary: str,
    date: str = "2026-07-07T00:00:00.000000Z",
    with_form: bool = True,
) -> dict[str, object]:
    content_items: list[dict[str, object]] = [
        {
            "type": "text_2_3",
            "text": (
                "<h2>Deine neue Rolle</h2>"
                "<ul><li>Build useful software</li><li>Improve quality</li></ul>"
            ),
        },
        {
            "type": "text_2_3",
            "text": "<h2>Deine Superpowers</h2><p>Engineering experience</p>",
        },
    ]
    if with_form:
        content_items.append(
            {
                "type": "form_builder",
                "form": {"handle": "application_form"},
            }
        )
    return {
        "id": job_id,
        "title": title,
        "slug": slug,
        "url": f"/jobs/{slug}",
        "permalink": f"https://www.nexplore.ch/jobs/{slug}",
        "api_url": (f"https://cms.nexplore.ch/api/collections/jobs/entries/{job_id}"),
        "collection": "jobs",
        "blueprint": "job",
        "status": "published",
        "published": True,
        "private": False,
        "parent_url": "/jobs",
        "date": date,
        "description": f"<p>{summary}</p>",
        "content_items": content_items,
        "job_categories": [
            {
                "title": "Software Engineering & Entwicklung",
                "slug": "entwicklung",
            }
        ],
    }


def catalog_fixture() -> list[dict[str, object]]:
    return [
        catalog_record(
            "bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
            slug="software_test_engineer_1",
            title="Software Test Engineer (m/w/d)",
            summary="60 - 100 % (flexibles Pensum) | Thun | Bern | Basel | Homeoffice",
        ),
        catalog_record(
            "bd56eeca-a466-404e-b233-162e43ebab87",
            slug="full_stack_software_engineer",
            title="Senior Full Stack Software Engineer (m/w/d)",
            summary=(
                "80 - 100 % | Thun | Bern | Basel | "
                "Homeoffice (Team trifft sich 1x pro Woche in Thun)"
            ),
            date="2026-07-02T00:00:00.000000Z",
        ),
        catalog_record(
            "62b9182c-6dbc-4ba4-9013-1e2146a84fa4",
            slug="wer-sind-wir",
            title="Wer sind wir?",
            summary="Informationen über Nexplore",
            with_form=False,
        ),
        catalog_record(
            "fdb66af8-83b6-4fb2-b92a-61e8ed2f3d5e",
            slug="spontanbewerbungen",
            title="Spontanbewerbungen",
            summary="Keine passende Stelle gefunden?",
        ),
    ]


def catalog_payload(records: list[dict[str, object]]) -> dict[str, object]:
    total = len(records)
    return {
        "data": records,
        "links": {"first": f"{NEXPLORE_JOBS_API_URL}?page=1", "next": None},
        "meta": {
            "current_page": 1,
            "last_page": 1,
            "path": NEXPLORE_JOBS_API_URL,
            "per_page": 1000,
            "to": total,
            "total": total,
        },
    }


def test_nexplore_collects_complete_catalog_and_excludes_non_vacancy_cards() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=catalog_payload(catalog_fixture()))

    result = NexploreJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert calls == [NEXPLORE_JOBS_API_URL]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Nexplore Switzerland vacancies from 4 official catalog records"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "nexplore"
    assert first.title == "Software Test Engineer (m/w/d)"
    assert first.company == "Nexplore AG"
    assert first.location == "Thun / Bern / Basel / Homeoffice, Switzerland"
    assert first.url == "https://www.nexplore.ch/jobs/software_test_engineer_1"
    assert first.apply_url == first.url
    assert first.posted_at == "2026-07-07"
    assert first.employment_type == "60–100%"
    assert first.description and "Deine neue Rolle" in first.description
    assert first.description and "- Build useful software" in first.description
    assert first.raw["categories"] == ["Software Engineering & Entwicklung"]
    assert result.jobs[1].posted_at == "2026-07-02"
    assert all(job.raw["slug"] not in {"wer-sind-wir", "spontanbewerbungen"} for job in result.jobs)


def test_nexplore_rejects_incomplete_catalog_metadata() -> None:
    payload = catalog_payload(catalog_fixture())
    payload["meta"]["total"] = 5  # type: ignore[index]
    parser = NexploreJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match="response is incomplete"):
        parser.search(LinkedInSearchRequest())


def test_nexplore_rejects_duplicate_or_unsafe_catalog_records() -> None:
    record = catalog_fixture()[0]
    duplicate = NexploreJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=catalog_payload([record, record]))
        )
    )
    unsafe_record = dict(record)
    unsafe_record["permalink"] = "https://evil.example/jobs/software_test_engineer_1"
    unsafe = NexploreJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=catalog_payload([unsafe_record]))
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete record"):
        unsafe.search(LinkedInSearchRequest())


def test_nexplore_rejects_missing_form_or_unknown_location() -> None:
    no_form_record = catalog_record(
        "bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
        slug="software_test_engineer_1",
        title="Software Test Engineer (m/w/d)",
        summary="60 - 100 % | Thun | Homeoffice",
        with_form=False,
    )
    unknown_location_record = catalog_record(
        "bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
        slug="software_test_engineer_1",
        title="Software Test Engineer (m/w/d)",
        summary="60 - 100 % | Berlin | Homeoffice",
    )

    def run(record: dict[str, object]) -> None:
        parser = NexploreJobsParser(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=catalog_payload([record]))
            )
        )
        parser.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="application form"):
        run(no_form_record)
    with pytest.raises(DirectCompanyRequestError, match="unknown location"):
        run(unknown_location_record)


def test_nexplore_wraps_catalog_request_failures() -> None:
    parser = NexploreJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_nexplore_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["nexplore"]
    assert isinstance(parser, NexploreJobsParser)
    assert parser.base_url == settings.nexplore_jobs_base_url
    assert parser.api_url == settings.nexplore_jobs_api_url

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Nexplore", "filters": {}},
            "sources": ["nexplore", "nexplore"],
        }
    )
    assert request.sources == ["nexplore"]


def test_nexplore_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": "bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
            "title": "Software Test Engineer (m/w/d)",
            "url": "https://www.nexplore.ch/jobs/software_test_engineer_1",
            "location": "Thun / Bern / Basel / Homeoffice, Switzerland",
            "workload": "60–100%",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="nexplore-bcff2b26-bae2-48e2-851d-f39ee1fbcb3d",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Nexplore import"
    assert stored["id"] == "nexplore-bcff2b26-bae2-48e2-851d-f39ee1fbcb3d"
