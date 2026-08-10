from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.aveniq import AveniqJobsParser
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def offer(
    *,
    job_id: int = 2672332,
    country_code: str = "CH",
    status: str = "published",
) -> dict[str, object]:
    slug = f"technical-account-manager-{job_id}"
    return {
        "id": job_id,
        "title": "Technical Account Manager",
        "company_name": "Aveniq AG",
        "slug": slug,
        "status": status,
        "country_code": country_code,
        "location": "Baden, Aargau, Schweiz",
        "locations": [
            {
                "city": "Baden",
                "state": "Aargau",
                "country": "Schweiz",
                "country_code": country_code,
            },
            {
                "city": "Bern",
                "state": "Bern",
                "country": "Schweiz",
                "country_code": country_code,
            },
        ],
        "careers_url": f"https://aveniq.recruitee.com/o/{slug}",
        "careers_apply_url": f"https://aveniq.recruitee.com/o/{slug}/c/new",
        "published_at": "2026-08-03 09:40:19 UTC",
        "employment_type_code": "fulltime_permanent",
        "experience_code": "experienced",
        "tags": ["80-100%", "IT Specialists"],
        "highlight": (
            "<p>Eine Herausforderung an der Schnittstelle von Technik &amp; Kundenbetreuung.</p>"
        ),
        "description": "<p>Gestalte die digitale Zukunft.</p>",
        "requirements": (
            "<h3>Das bringst du mit:</h3><ul><li>Cloud-Erfahrung</li><li>Teamgeist</li></ul>"
        ),
        "salary": {
            "min": 120000,
            "max": 140000,
            "currency": "CHF",
            "period": "year",
        },
    }


def test_aveniq_scans_and_normalizes_full_recruitee_catalog() -> None:
    records = [offer(), offer(job_id=2672333)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"offers": records})

    parser = AveniqJobsParser(
        base_url="https://aveniq.recruitee.com/",
        api_url="https://aveniq.recruitee.com/api/offers/",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 Aveniq vacancies from the full Recruitee catalog")
    assert len(requests) == 1
    assert requests[0].url == "https://aveniq.recruitee.com/api/offers/"
    assert requests[0].headers["referer"] == parser.base_url
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "aveniq"
    assert first.title == "Technical Account Manager"
    assert first.company == "Aveniq AG"
    assert first.location == "Baden, Aargau, Schweiz; Bern, Bern, Schweiz"
    assert first.url == records[0]["careers_url"]
    assert first.apply_url == records[0]["careers_apply_url"]
    assert first.posted_at == "2026-08-03 09:40:19 UTC"
    assert first.employment_type == "80-100%"
    assert first.seniority == "Experienced"
    assert first.description == (
        "Eine Herausforderung an der Schnittstelle von Technik & Kundenbetreuung.\n\n"
        "Gestalte die digitale Zukunft.\n\n"
        "Das bringst du mit:\n- Cloud-Erfahrung\n- Teamgeist"
    )
    assert first.salary == "120,000-140,000 CHF year"
    assert first.salary_min == 120000
    assert first.salary_max == 140000
    assert first.salary_currency == "CHF"
    assert first.salary_unit == "year"
    assert first.raw["id"] == 2672332


def test_aveniq_uses_employment_code_without_percentage_tag() -> None:
    record = offer()
    record["tags"] = ["IT Specialists"]

    job = AveniqJobsParser().normalize_job(record)

    assert job.employment_type == "Full-time, permanent"


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"jobs": []}, "missing its offers catalog"),
        ({"offers": [offer(country_code="DE")]}, "non-Swiss vacancy"),
        ({"offers": [offer(status="draft")]}, "non-Swiss vacancy"),
        ({"offers": [offer(), offer()]}, "duplicate vacancy IDs"),
    ],
)
def test_aveniq_rejects_invalid_catalog(payload: object, message: str) -> None:
    parser = AveniqJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_aveniq_enforces_catalog_limit() -> None:
    parser = AveniqJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"offers": [offer(), offer(job_id=2672333)]},
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_aveniq_wraps_api_failures() -> None:
    parser = AveniqJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_aveniq_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["aveniq"]
    assert isinstance(parser, AveniqJobsParser)
    assert parser.base_url == settings.aveniq_jobs_base_url
    assert parser.api_url == settings.aveniq_jobs_api_url
    assert parser.max_jobs == settings.aveniq_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Aveniq", "filters": {}},
            "sources": ["aveniq", "aveniq"],
        }
    )
    assert request.sources == ["aveniq"]


def test_aveniq_jobs_render_as_direct_company_imports() -> None:
    parsed = AveniqJobsParser().normalize_job(offer())

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="aveniq-2672332",
        added_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "aveniq-2672332"
    assert stored["logo"] == "company"
    assert stored["department"] == "Aveniq import"
    assert stored["company"] == "Aveniq AG"
