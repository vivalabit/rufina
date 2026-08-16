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
from app.services.parsers.companies.gsk_switzerland import (
    GSK_COUNTRY,
    GSK_RESULTS_PER_PAGE,
    GskSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(index: int, *, foreign_primary: bool = False) -> dict[str, object]:
    primary = (
        "Collegeville, Pennsylvania, United States of America"
        if foreign_primary
        else "Baar, Switzerland"
    )
    country = "United States of America" if foreign_primary else GSK_COUNTRY
    locations = [primary, "Zug, Switzerland"] if foreign_primary else [primary]
    return {
        "type": "Full time",
        "descriptionTeaser": f"Short description for GSK role {index}.",
        "reqId": f"Job Code: J{index:06d}",
        "city": "Collegeville" if foreign_primary else "Baar",
        "country": country,
        "applyUrl": (
            "https://gsk.wd5.myworkdayjobs.com/GSKCareers/job/"
            f"Baar-Onyx/GSK-Role-{index}_{440000 + index}/apply"
        ),
        "jobId": str(440000 + index),
        "title": f"GSK Role {index}",
        "jobSeqNo": f"GHVGPAGB{440000 + index}EXTERNALENGB",
        "postedDate": "2026-08-12T00:00:00.000+0000",
        "cityStateCountry": primary,
        "location": primary,
        "category": "Medical and Clinical",
        "remoteType": "Hybrid (Remote & On-site)",
        "multi_location": locations,
        "multi_location_array": [{"location": location} for location in locations],
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int | None = None,
    selected_country: str = GSK_COUNTRY,
) -> dict[str, object]:
    declared_total = len(records) if total is None else total
    return {
        "refineSearch": {
            "status": 200,
            "hits": len(records),
            "totalHits": declared_total,
            "data": {
                "jobs": records,
                "aggregations": [
                    {"field": "remoteType", "value": {"Hybrid": declared_total}},
                    {"field": "country", "value": {GSK_COUNTRY: declared_total}},
                ],
                "ui_selections": {"country": [selected_country]},
            },
        }
    }


def session_html(token: str = "csrf-token") -> str:
    return f'<html><script>phApp.sessionParams = {{"csrfToken":"{token}"}};</script></html>'


def detail_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "description": (
            "<h2>Position summary</h2><p>Help unite science and technology.</p>"
            "<ul><li>Lead medical strategy</li><li>Support patients</li></ul>"
        ),
        "structureData": {
            "datePosted": "2026-08-12",
            "description": "<p>Structured fallback.</p>",
            "jobLocation": {
                "address": {
                    "addressLocality": "Baar",
                    "addressRegion": "",
                    "addressCountry": GSK_COUNTRY,
                }
            },
        },
    }


def ddo_html(payload: dict[str, object], *, canonical_url: str | None = None) -> str:
    canonical = f'<link rel="canonical" href="{canonical_url}">' if canonical_url else ""
    return (
        f"<html><head>{canonical}<script>var phApp = {{}}; phApp.ddo = "
        f"{json.dumps(payload)}; phApp.experimentData = {{}};</script></head></html>"
    )


def detail_html(record: dict[str, object]) -> str:
    return ddo_html(
        {
            "jobDetail": {
                "status": 200,
                "hits": 1,
                "totalHits": 1,
                "data": {"job": detail_record(record)},
            }
        },
        canonical_url=(
            "https://jobs.gsk.test/gb/en/job/"
            f"{record['jobSeqNo']}/GSK-Role-{record['jobId']}"
        ),
    )


def parser_with(
    transport: httpx.BaseTransport,
    **kwargs: object,
) -> GskSwitzerlandJobsParser:
    return GskSwitzerlandJobsParser(
        base_url=(
            "https://jobs.gsk.test/gb/en/search-results?"
            "keywords=&location=Switzerland&lang=en-gb"
        ),
        page_workers=1,
        detail_workers=1,
        transport=transport,
        **kwargs,
    )


def test_gsk_fetches_every_country_facet_page_and_enriches_details() -> None:
    records = [listing_record(index, foreign_primary=index == 0) for index in range(11)]
    listing_offsets: list[int] = []
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/search-results"):
            return httpx.Response(200, text=session_html(), request=request)
        if request.method == "POST":
            assert request.url.path == "/widgets"
            assert request.headers["X-CSRF-TOKEN"] == "csrf-token"
            body = json.loads(request.content)
            assert body["selected_fields"] == {"country": [GSK_COUNTRY]}
            assert body["size"] == GSK_RESULTS_PER_PAGE
            offset = body["from"]
            listing_offsets.append(offset)
            return httpx.Response(
                200,
                json=listing_payload(records[offset : offset + 10], total=len(records)),
                request=request,
            )
        detail_requests.append(request.url.path)
        sequence = request.url.path.rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == sequence)
        return httpx.Response(200, text=detail_html(record), request=request)

    result = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert listing_offsets == [0, 10]
    assert len(detail_requests) == 11
    assert result.message == (
        "Scanned 11 verified GSK Switzerland vacancies from 11 Phenom country "
        "records across 2 page requests in 1 catalog pass(es)"
    )
    assert len(result.jobs) == 11
    first = result.jobs[0]
    assert first.source == "gsk_switzerland"
    assert first.title == "GSK Role 0"
    assert first.company == "GSK"
    assert first.location == "Zug, Switzerland"
    assert first.url.endswith("/GSK-Role-440000")
    assert first.apply_url.endswith("/GSK-Role-0_440000/apply")
    assert first.posted_at == "2026-08-12T00:00:00.000+0000"
    assert first.employment_type == "Full time"
    assert first.description == (
        "Position summary\nHelp unite science and technology.\n"
        "- Lead medical strategy\n- Support patients"
    )
    assert first.raw["listing_offset"] == 0
    assert first.raw["listing_pass"] == 1
    assert first.raw["total_available"] == 11


def test_gsk_reconciles_a_shifted_catalog() -> None:
    records = [listing_record(index) for index in range(11)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.method == "GET" and request.url.path.endswith("/search-results"):
            return httpx.Response(200, text=session_html(), request=request)
        if request.method == "POST":
            calls += 1
            offset = json.loads(request.content)["from"]
            page = records[offset : offset + 10]
            if calls == 2:
                page = [records[9]]
            return httpx.Response(
                200,
                json=listing_payload(page, total=len(records)),
                request=request,
            )
        sequence = request.url.path.rsplit("/", maxsplit=1)[-1]
        record = next(item for item in records if item["jobSeqNo"] == sequence)
        return httpx.Response(200, text=detail_html(record), request=request)

    result = parser_with(
        httpx.MockTransport(handler),
        max_catalog_passes=2,
    ).search(LinkedInSearchRequest())

    assert calls == 4
    assert len(result.jobs) == 11
    assert all(job.raw["listing_pass"] == 2 for job in result.jobs)


def test_gsk_preserves_listing_when_detail_fails() -> None:
    record = listing_record(1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/search-results"):
            return httpx.Response(200, text=session_html(), request=request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json=listing_payload([record]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = parser_with(httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    ).jobs[0]

    assert job.description == "Short description for GSK role 1."
    assert job.location == "Baar, Switzerland"
    assert job.url.endswith(str(record["jobSeqNo"]))
    assert job.apply_url == record["applyUrl"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda payload: payload["refineSearch"]["data"]["ui_selections"].update(  # type: ignore[index,union-attr]
                {"country": ["United Kingdom"]}
            ),
            "did not preserve its country selection",
        ),
        (
            lambda payload: payload["refineSearch"]["data"]["aggregations"][1][  # type: ignore[index]
                "value"
            ].update({GSK_COUNTRY: 99}),
            "invalid country count",
        ),
    ],
)
def test_gsk_rejects_unverified_country_facet(mutator: object, match: str) -> None:
    payload = listing_payload([listing_record(1)])
    mutator(payload)  # type: ignore[operator]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=session_html(), request=request)
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=match):
        parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_gsk_rejects_record_without_swiss_location() -> None:
    record = listing_record(1)
    record.update(
        {
            "country": "Germany",
            "cityStateCountry": "Munich, Germany",
            "location": "Munich, Germany",
            "multi_location": ["Munich, Germany"],
            "multi_location_array": [{"location": "Munich, Germany"}],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=session_html(), request=request)
        return httpx.Response(
            200,
            json=listing_payload([record]),
            request=request,
        )

    with pytest.raises(DirectCompanyRequestError, match="without a Swiss location"):
        parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_gsk_rejects_malformed_truncated_and_oversized_catalogs() -> None:
    def parser_for_payload(
        payload: dict[str, object],
        **kwargs: object,
    ) -> GskSwitzerlandJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, text=session_html(), request=request)
            return httpx.Response(200, json=payload, request=request)

        return parser_with(httpx.MockTransport(handler), **kwargs)

    malformed = parser_for_payload(
        {"refineSearch": {"status": 200, "hits": 1, "totalHits": 1, "data": {}}}
    )
    truncated = parser_for_payload(
        listing_payload([listing_record(1)], total=2),
        max_catalog_passes=1,
    )
    oversized = parser_for_payload(
        listing_payload(
            [listing_record(index) for index in range(10)],
            total=21,
        ),
        max_pages=2,
    )

    with pytest.raises(DirectCompanyRequestError, match="invalid jobs"):
        malformed.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="1 unique vacancies of 2"):
        truncated.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 2"):
        oversized.search(LinkedInSearchRequest())


def test_gsk_accepts_verified_empty_catalog() -> None:
    payload = listing_payload([], total=0)
    payload["refineSearch"]["data"]["aggregations"][1]["value"] = {}  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=session_html(), request=request)
        return httpx.Response(200, json=payload, request=request)

    result = parser_with(httpx.MockTransport(handler)).search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 verified GSK Switzerland vacancies")


def test_gsk_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["gsk_switzerland"]

    assert isinstance(parser, GskSwitzerlandJobsParser)
    assert parser.base_url == settings.gsk_switzerland_jobs_base_url
    assert parser.max_pages == settings.gsk_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.gsk_switzerland_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "GSK Switzerland", "filters": {}},
            "sources": ["gsk_switzerland", "gsk_switzerland"],
        }
    )
    assert request.sources == ["gsk_switzerland"]

    record = listing_record(1)
    record["detail"] = detail_record(record)
    stored = parsed_job_to_stored_job(
        parser.normalize_job(record),
        job_id="gsk_switzerland-445481",
        added_at=datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "GSK Switzerland import"
    assert stored["company"] == "GSK"
