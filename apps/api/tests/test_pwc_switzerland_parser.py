from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.pwc_switzerland import (
    PwcSwitzerlandJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def viewkey(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def listing_record(
    index: int,
    *,
    language: str = "en",
    country: str = "Switzerland",
) -> dict[str, object]:
    key = viewkey(index)
    german = language == "de"
    return {
        "id": str(10_140_000 + index),
        "hk_id": "1008576",
        "viewkey": key,
        "title": f"{'Berater' if german else 'Consultant'} {index}",
        "attributes": {
            "10": ["Graduates"],
            "20": ["Zürich", "Bern"] if index == 0 else ["Zürich"],
            "30": ["Advisory"],
            "40": ["Full-time", "Part-time"],
            "50": ["Consulting"],
        },
        "szas": {
            "sza_reference_code": f"{600_000 + index}WD",
            "sza_title": f"{'Berater' if german else 'Consultant'} {index}",
            "sza_apply_link": (
                "https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers/"
                f"job/Zurich/Consultant-{index}_{600_000 + index}WD/apply"
            ),
            "sza_location.country": country,
            "sza_location.city": "Zürich",
            "sza_introduction": "Gestalte Vertrauen." if german else "Build trust.",
            "sza_tasks": "<ul><li>Lead projects</li><li>Advise clients</li></ul>",
            "sza_requirements": "<ul><li>University degree</li></ul>",
            "sza_company_profil": (
                "Bei PwC Schweiz unterstützen wir unsere Kunden."
                if german
                else "At PwC Switzerland, we help clients build trust."
            ),
            "sza_pensum": "80-100%",
            "sza_employment_type": "Permanent employment",
        },
        "links": {"directlink": (f"https://jobs.pwc.ch/job-vacancies/consultant-{index}/{key}")},
        "start_date": "2026-08-14T22:00:00Z",
        "end_date": "2036-08-11T21:59:59Z",
        "language": language,
    }


def payload(
    records: list[dict[str, object]],
    *,
    total: int,
    offset: int,
    medium_id: str = "1000311",
) -> dict[str, object]:
    return {
        "medium_id": medium_id,
        "medium_name": None,
        "offset": offset,
        "total": total,
        "jobs": records,
        "filtercount": None,
    }


def test_pwc_fetches_complete_multilingual_catalog() -> None:
    records = [
        listing_record(
            index,
            language="de" if index % 3 == 0 else "en",
            country="Liechtenstein" if index == 97 else "Switzerland",
        )
        for index in range(98)
    ]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["lang"] == "en"
        assert request.url.params["limit"] == "96"
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        return httpx.Response(
            200,
            json=payload(
                records[offset : offset + 96],
                total=len(records),
                offset=offset,
            ),
            request=request,
        )

    result = PwcSwitzerlandJobsParser(
        api_url="https://api.pwc.test/public/v1/medium/1000311/jobs",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert result.message == (
        "Scanned 98 PwC Switzerland vacancies from 98 Prospective records "
        "across 2 API page requests in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 98
    first = result.jobs[0]
    assert first.source == "pwc_switzerland"
    assert first.title == "Berater 0"
    assert first.company == "PwC Switzerland"
    assert first.location == "Zürich; Bern"
    assert first.url == (
        "https://jobs.pwc.ch/job-vacancies/consultant-0/00000000-0000-4000-8000-000000000000"
    )
    assert first.apply_url and first.apply_url.endswith("_600000WD/apply")
    assert first.posted_at == "2026-08-14T22:00:00Z"
    assert first.employment_type == ("Permanent employment, 80-100%, Full-time, Part-time")
    assert first.seniority == "Graduates"
    assert first.description == (
        "Introduction\nGestalte Vertrauen.\n\n"
        "Responsibilities\n- Lead projects\n- Advise clients\n\n"
        "Requirements\n- University degree\n\n"
        "About PwC Switzerland\n"
        "Bei PwC Schweiz unterstützen wir unsere Kunden."
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 98
    assert result.jobs[-1].raw["szas"]["sza_location.country"] == "Liechtenstein"


def test_pwc_retries_shifted_pages_until_all_ids_are_seen() -> None:
    records = [listing_record(index) for index in range(98)]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        if offset == 0:
            page_records = records[:96]
        elif requested_offsets.count(96) == 1:
            page_records = [records[95], records[96]]
        else:
            page_records = records[96:]
        return httpx.Response(
            200,
            json=payload(page_records, total=len(records), offset=offset),
            request=request,
        )

    result = PwcSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 98
    assert result.message.endswith("across 4 API page requests in 2 catalog pass(es)")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda record: record.update({"hk_id": "foreign"}), "out-of-scope"),
        (
            lambda record: record["szas"].update(  # type: ignore[union-attr]
                {"sza_location.country": "Germany"}
            ),
            "out-of-scope",
        ),
        (
            lambda record: record["links"].update(  # type: ignore[union-attr]
                {"directlink": "https://evil.test/job/1"}
            ),
            "out-of-scope",
        ),
    ],
)
def test_pwc_rejects_out_of_scope_records(mutate: object, message: str) -> None:
    record = listing_record(1)
    mutate(record)  # type: ignore[operator]
    parser = PwcSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=payload([record], total=1, offset=0),
                request=request,
            )
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_pwc_rejects_wrong_medium_truncated_and_oversized_catalogs() -> None:
    wrong_medium = PwcSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=payload(
                    [listing_record(1)],
                    total=1,
                    offset=0,
                    medium_id="other",
                ),
                request=request,
            )
        )
    )
    truncated = PwcSwitzerlandJobsParser(
        max_catalog_passes=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=payload([listing_record(1)], total=2, offset=0),
                request=request,
            )
        ),
    )
    oversized = PwcSwitzerlandJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=payload(
                    [listing_record(index) for index in range(96)],
                    total=97,
                    offset=0,
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected medium ID"):
        wrong_medium.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 records instead of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_pwc_wraps_request_failures() -> None:
    parser = PwcSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_pwc_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["pwc_switzerland"]

    assert isinstance(parser, PwcSwitzerlandJobsParser)
    assert parser.base_url == settings.pwc_switzerland_jobs_base_url
    assert parser.api_url == settings.pwc_switzerland_jobs_api_url
    assert parser.max_pages == settings.pwc_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.pwc_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "PwC Switzerland", "filters": {}},
            "sources": ["pwc_switzerland", "pwc_switzerland"],
        }
    )
    assert request.sources == ["pwc_switzerland"]


def test_pwc_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="pwc_switzerland-10140001",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "PwC Switzerland import"
    assert stored["company"] == "PwC Switzerland"


def test_pwc_accepts_workday_job_landing_page_without_apply_suffix() -> None:
    from app.services.parsers.companies.pwc_switzerland import validate_listing_record
    record = listing_record(1)
    record["szas"]["sza_apply_link"] = record["szas"]["sza_apply_link"].removesuffix("/apply")
    validate_listing_record(record)
