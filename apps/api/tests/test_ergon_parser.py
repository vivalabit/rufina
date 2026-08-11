from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.ergon import ErgonJobsParser
from app.services.vacancy_search import create_vacancy_search_runner


def offer(
    *,
    job_id: int = 2587674,
    country_code: str = "CH",
    status: str = "published",
    company_name: str = "Ergon Informatik AG",
) -> dict[str, object]:
    slug = f"senior-fullstack-software-engineer-{job_id}"
    return {
        "id": job_id,
        "title": "Senior Fullstack Software Engineer",
        "company_name": company_name,
        "slug": slug,
        "status": status,
        "country_code": country_code,
        "location": "Zürich, Zürich, Schweiz",
        "locations": [
            {
                "city": "Zürich",
                "state": "Zürich",
                "country": "Schweiz",
                "country_code": country_code,
            }
        ],
        "careers_url": f"https://apply.ergon.ch/o/{slug}",
        "careers_apply_url": f"https://apply.ergon.ch/o/{slug}/c/new",
        "published_at": "2026-04-30 13:27:41 UTC",
        "employment_type_code": "fulltime_permanent",
        "experience_code": "experienced",
        "highlight": "<p>Entwickle anspruchsvolle Softwarelösungen.</p>",
        "description": "<p>Du arbeitest in einem autonomen Team.</p>",
        "requirements": "<ul><li>Java oder Kotlin</li><li>Teamgeist</li></ul>",
        "salary": {
            "min": "110000",
            "max": "165000",
            "currency": "CHF",
            "period": "year",
        },
    }


def test_ergon_scans_and_normalizes_full_recruitee_catalog() -> None:
    records = [offer(), offer(job_id=2587675)]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"offers": records})

    parser = ErgonJobsParser(transport=httpx.MockTransport(handler))

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Ergon vacancies from the full Recruitee catalog"
    )
    assert len(requests) == 1
    assert requests[0].url == "https://apply.ergon.ch/api/offers/"
    assert requests[0].headers["referer"] == parser.base_url
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "ergon"
    assert first.title == "Senior Fullstack Software Engineer"
    assert first.company == "Ergon Informatik AG"
    assert first.location == "Zürich, Zürich, Schweiz"
    assert first.url == records[0]["careers_url"]
    assert first.apply_url == records[0]["careers_apply_url"]
    assert first.posted_at == "2026-04-30 13:27:41 UTC"
    assert first.employment_type == "Full-time, permanent"
    assert first.seniority == "Experienced"
    assert first.description == (
        "Entwickle anspruchsvolle Softwarelösungen.\n\n"
        "Du arbeitest in einem autonomen Team.\n\n"
        "- Java oder Kotlin\n- Teamgeist"
    )
    assert first.salary == "110,000-165,000 CHF year"
    assert first.salary_min == 110000
    assert first.salary_max == 165000
    assert first.salary_currency == "CHF"
    assert first.salary_unit == "year"
    assert first.raw["id"] == 2587674


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"jobs": []}, "missing its offers catalog"),
        ({"offers": [offer(country_code="DE")]}, "non-Swiss vacancy"),
        ({"offers": [offer(status="draft")]}, "non-Swiss vacancy"),
        ({"offers": [offer(company_name="Other AG")]}, "non-Swiss vacancy"),
        ({"offers": [offer(), offer()]}, "duplicate vacancy IDs"),
    ],
)
def test_ergon_rejects_invalid_catalog(payload: object, message: str) -> None:
    parser = ErgonJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_ergon_enforces_catalog_limit() -> None:
    parser = ErgonJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"offers": [offer(), offer(job_id=2587675)]},
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_ergon_wraps_api_failures() -> None:
    parser = ErgonJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_ergon_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ergon"]
    assert isinstance(parser, ErgonJobsParser)
    assert parser.base_url == settings.ergon_jobs_base_url
    assert parser.api_url == settings.ergon_jobs_api_url
    assert parser.max_jobs == settings.ergon_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Ergon", "filters": {}},
            "sources": ["ergon", "ergon"],
        }
    )
    assert request.sources == ["ergon"]


def test_ergon_jobs_render_as_direct_company_imports() -> None:
    parsed = ErgonJobsParser().normalize_job(offer())

    stored = parsed_job_to_stored_job(
        parsed,
        job_id="ergon-2587674",
        added_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "ergon-2587674"
    assert stored["logo"] == "company"
    assert stored["department"] == "Ergon import"
    assert stored["company"] == "Ergon Informatik AG"
