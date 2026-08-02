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
from app.services.parsers.companies.die_post import DiePostJobsParser, parse_detail_html
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    index: int,
    *,
    locale: str = "en_US",
    job_id: str | None = None,
) -> dict[str, object]:
    return {
        "jobLocationShort": [
            "Zurich|Zurich|ZH|Switzerland|CHE ",
            "Berlin|Berlin|BE|Germany|DEU ",
        ],
        "supportedLocales": [locale],
        "filter1": ["Informatics and digital business"],
        "filter2": ["Applicants with professional experience"],
        "cust_WorkingTimeMin": ["80"],
        "cust_WorkingTimeMax": ["100"],
        "cust_brandCompanyJobSearch": ["Swiss Post Ltd"],
        "unifiedStandardEnd": "8/31/26",
        "brandUrl": "PostKG",
        "unifiedUrlTitle": f"Platform-Engineer-{index}",
        "unifiedStandardStart": "7/14/26" if locale == "en_US" else "14.07.26",
        "id": job_id or str(74_000 + index),
        "unifiedStandardTitle": f"Platform Engineer {index} ({locale})",
        "urlTitle": f"Platform-Engineer-{index}",
    }


def detail_html(*, canonical_url: str, job_id: str) -> str:
    return f"""
    <html>
      <head><link rel="canonical" href="{canonical_url}/" /></head>
      <body>
        <a class="unify-apply-now" href="/talentcommunity/apply/{job_id}/?locale=en_US">
          Apply now
        </a>
        <div class="jobDisplay"><div class="job"><div class="jobColumnTwo">
          <span class="rtltextaligneligible">
            <p>Build reliable services for Switzerland.</p>
            <h2>Your tasks</h2>
            <ul><li>Automate the platform</li><li>Improve reliability</li></ul>
          </span>
        </div></div></div>
      </body>
    </html>
    """


def test_die_post_parser_fetches_every_locale_page_and_enriches_unique_jobs() -> None:
    locale_records = {
        "en_US": [listing_record(index) for index in range(12)],
        "de_DE": [
            listing_record(0, locale="de_DE", job_id="74000"),
            listing_record(12, locale="de_DE"),
        ],
        "fr_FR": [],
        "it_IT": [],
    }
    listing_requests: list[tuple[str, int]] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content)
            locale = body["locale"]
            page = body["pageNumber"]
            listing_requests.append((locale, page))
            records = locale_records[locale]
            start = page * 10
            return httpx.Response(
                200,
                json={
                    "totalJobs": len(records),
                    "jobSearchResult": [
                        {"response": record} for record in records[start : start + 10]
                    ],
                },
            )
        if request.method == "GET" and "/job/" in request.url.path:
            detail_requests.append(request.url.path)
            job_id = request.url.path.rsplit("/", 1)[-1].split("-", 1)[0]
            return httpx.Response(
                200,
                text=detail_html(canonical_url=str(request.url), job_id=job_id),
            )
        return httpx.Response(404)

    parser = DiePostJobsParser(
        base_url="https://post.example.test/search?locale=en_US",
        detail_workers=4,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_requests == [
        ("en_US", 0),
        ("en_US", 1),
        ("de_DE", 0),
        ("fr_FR", 0),
        ("it_IT", 0),
    ]
    assert len(detail_requests) == 13
    assert result.status == "completed"
    assert result.message == "Scanned 13 Die Post vacancies across 5 API pages in 4 locales"
    assert len(result.jobs) == 13
    first = result.jobs[0]
    assert first.source == "die_post"
    assert first.title == "Platform Engineer 0 (en_US)"
    assert first.company == "Swiss Post Ltd"
    assert first.location == "Zurich, Berlin DEU"
    assert first.posted_at == "2026-07-14"
    assert first.employment_type == "80–100%"
    assert first.seniority == "Applicants with professional experience"
    assert first.description == (
        "Build reliable services for Switzerland.\n\nYour tasks\n\n"
        "- Automate the platform\n- Improve reliability"
    )
    assert first.apply_url == (
        "https://post.example.test/talentcommunity/apply/74000/?locale=en_US"
    )
    assert first.raw["listing_page"] == 0
    assert first.raw["available_locales"] == ["en_US", "de_DE"]


def test_die_post_parser_keeps_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            records = [listing_record(7)] if body["locale"] == "en_US" else []
            return httpx.Response(
                200,
                json={
                    "totalJobs": len(records),
                    "jobSearchResult": [{"response": record} for record in records],
                },
            )
        return httpx.Response(503)

    parser = DiePostJobsParser(
        base_url="https://post.example.test/search?locale=en_US",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest())

    assert len(result.jobs) == 1
    assert result.jobs[0].title == "Platform Engineer 7 (en_US)"
    assert result.jobs[0].location == "Zurich, Berlin DEU"
    assert result.jobs[0].description is None
    assert result.jobs[0].raw["detail_error"]


def test_die_post_parser_repeats_unstable_pages_until_all_ids_are_seen() -> None:
    english_pass = 0
    listing_requests: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal english_pass
        if request.method == "POST":
            body = json.loads(request.content)
            locale = body["locale"]
            page = body["pageNumber"]
            listing_requests.append((locale, page))
            if locale != "en_US":
                return httpx.Response(
                    200,
                    json={"totalJobs": 0, "jobSearchResult": []},
                )
            if page == 0:
                records = [listing_record(index) for index in range(10)]
            elif english_pass == 0:
                records = [listing_record(8), listing_record(9)]
                english_pass += 1
            else:
                records = [listing_record(10), listing_record(11)]
            return httpx.Response(
                200,
                json={
                    "totalJobs": 12,
                    "jobSearchResult": [{"response": record} for record in records],
                },
            )
        if request.method == "GET":
            job_id = request.url.path.rsplit("/", 1)[-1].split("-", 1)[0]
            return httpx.Response(
                200,
                text=detail_html(canonical_url=str(request.url), job_id=job_id),
            )
        return httpx.Response(404)

    parser = DiePostJobsParser(
        base_url="https://post.example.test/search?locale=en_US",
        detail_workers=1,
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert listing_requests[:4] == [
        ("en_US", 0),
        ("en_US", 1),
        ("en_US", 0),
        ("en_US", 1),
    ]
    assert len(result.jobs) == 12
    assert {job.raw["id"] for job in result.jobs} == {
        str(74_000 + index) for index in range(12)
    }
    assert result.message == "Scanned 12 Die Post vacancies across 7 API pages in 4 locales"


def test_die_post_detail_parser_supports_apprenticeship_layout() -> None:
    detail = parse_detail_html(
        """
        <html><head><link rel="canonical" href="/job/apprentice/74304-de_DE/" /></head>
        <body><div id="search-wrapper">
          <span itemprop="description">
            <p>Begin your retail apprenticeship with Swiss Post.</p>
            <ul><li>Advise customers</li><li>Learn postal services</li></ul>
          </span>
          <span itemprop="description"><div id="contactDetails">Recruiting team</div></span>
        </div><a class="unify-apply-now" href="/apply/74304">Apply</a></body></html>
        """,
        page_url="https://post.example.test/default/job/apprentice/74304-de_DE",
    )

    assert detail["description"] == (
        "Begin your retail apprenticeship with Swiss Post.\n\n"
        "- Advise customers\n- Learn postal services"
    )
    assert detail["canonical_url"] == (
        "https://post.example.test/job/apprentice/74304-de_DE/"
    )
    assert detail["apply_url"] == "https://post.example.test/apply/74304"


def test_die_post_parser_rejects_invalid_jobs_payload() -> None:
    parser = DiePostJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"totalJobs": 4, "jobSearchResult": {}},
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobSearchResult"):
        parser.search(LinkedInSearchRequest())


def test_die_post_parser_does_not_silently_truncate_above_page_limit() -> None:
    parser = DiePostJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "totalJobs": 21,
                    "jobSearchResult": [
                        {"response": listing_record(index)} for index in range(10)
                    ],
                },
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit of 2"):
        parser.search(LinkedInSearchRequest())


def test_die_post_is_registered_as_a_direct_company_source() -> None:
    runner = create_vacancy_search_runner(Settings())

    assert isinstance(runner.parsers["die_post"], DiePostJobsParser)
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Die Post", "filters": {}},
            "sources": ["die_post", "die_post"],
        }
    )
    assert request.sources == ["die_post"]


def test_die_post_jobs_render_as_direct_company_imports() -> None:
    parser = DiePostJobsParser()
    job = parser.normalize_job(listing_record(1))
    stored = parsed_job_to_stored_job(
        job,
        job_id="die_post-74001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Die Post import"
