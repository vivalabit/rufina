from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bearingpoint_switzerland import (
    BearingpointSwitzerlandJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def official_records() -> list[dict[str, object]]:
    return [
        {
            "job_id": "7760115",
            "title": "Senior Consultant Operations",
            "location": "Zürich",
            "locale": "de",
        },
        {
            "job_id": "7465039",
            "title": "Junior Consultant Banking",
            "location": "Genève",
            "locale": "en",
        },
    ]


def listing_html(records: list[dict[str, object]]) -> str:
    cards = "".join(
        """
        <a href="/de-ch/karriere/stellenangebote/agebote/?id=T{job_id}"
           class="panel one-click">
          <div class="row">
            <div class="columns job-title"><h3 class="panel-header">{title}</h3></div>
            <div class="columns job-info">{location}</div>
          </div>
        </a>
        """.format(**record)
        for record in records
    )
    return f"""
    <html><body>
      <a href="/de-ch/" class="logo" aria-label="Logo von BearingPoint"></a>
      <h2 class="jobs-title">{len(records)} Stellen verfügbar</h2>
      <div class="jobs">{cards}</div>
    </body></html>
    """


def feed_item(record: dict[str, object], index: int) -> dict[str, object]:
    job_id = str(record["job_id"])
    title = str(record["title"])
    locale_prefix = "/en" if record["locale"] == "en" else ""
    description = "<p>Shape the future.</p><ul><li>Lead client projects</li></ul>"
    published_at = "2026-05-19T09:30:00+02:00"
    return {
        "id": f"00000000-0000-4000-8000-{index:012d}",
        "title": title,
        "url": (
            f"https://bearingpointag.teamtailor.com{locale_prefix}/jobs/"
            f"{job_id}-consultant"
        ),
        "date_published": published_at,
        "content_html": description,
        "_jobposting": {
            "@context": "http://schema.org/",
            "@type": "JobPosting",
            "title": title,
            "description": description,
            "identifier": {
                "@type": "PropertyValue",
                "name": "BearingPoint AG",
                "value": int(job_id),
            },
            "datePosted": published_at,
            "employmentType": "FULL_TIME",
            "hiringOrganization": {
                "@type": "Organization",
                "name": "BearingPoint AG",
                "sameAs": "https://bearingpointag.teamtailor.com",
            },
            "jobLocation": [
                {
                    "@type": "Place",
                    "address": {
                        "@type": "PostalAddress",
                        "addressLocality": record["location"],
                        "addressCountry": "CH",
                    },
                }
            ],
        },
    }


def feed_payload(
    records: list[dict[str, object]],
    *,
    locale: str,
) -> dict[str, object]:
    prefix = "/en" if locale == "en" else ""
    selected = [record for record in records if record["locale"] == locale]
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "BearingPoint AG",
        "home_page_url": f"https://bearingpointag.teamtailor.com{prefix}/jobs",
        "feed_url": f"https://bearingpointag.teamtailor.com{prefix}/jobs.json",
        "items": [
            feed_item(record, index)
            for index, record in enumerate(selected, 1 if locale == "de" else 100)
        ],
    }


def response_handler(
    records: list[dict[str, object]],
    requests: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/jobs.json":
            return httpx.Response(
                200, json=feed_payload(records, locale="de"), request=request
            )
        if request.url.path == "/en/jobs.json":
            return httpx.Response(
                200, json=feed_payload(records, locale="en"), request=request
            )
        return httpx.Response(200, text=listing_html(records), request=request)

    return handler


def test_bearingpoint_scans_complete_bilingual_swiss_catalog() -> None:
    records = official_records()
    requests: list[httpx.Request] = []
    result = BearingpointSwitzerlandJobsParser(
        transport=httpx.MockTransport(response_handler(records, requests))
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 3
    assert requests[0].url.params["country"] == "CH"
    assert requests[1].url.params["country"] == "Switzerland"
    assert requests[2].url.params["country"] == "Switzerland"
    assert len({request.url.params["_"] for request in requests}) == 1
    assert result.message == (
        "Scanned 2 BearingPoint Switzerland vacancies from the complete official "
        "catalog and 2 Teamtailor locale feeds in 1 catalog pass(es) across 3 requests"
    )
    assert len(result.jobs) == 2
    job = result.jobs[0]
    assert job.source == "bearingpoint_switzerland"
    assert job.title == "Senior Consultant Operations"
    assert job.company == "BearingPoint AG"
    assert job.location == "Zürich"
    assert job.url == (
        "https://www.bearingpoint.com/de-ch/karriere/stellenangebote/agebote/"
        "?id=T7760115&country=CH"
    )
    assert job.apply_url == (
        "https://bearingpointag.teamtailor.com/jobs/7760115-consultant/"
        "applications/new"
    )
    assert job.posted_at == "2026-05-19T09:30:00+02:00"
    assert job.employment_type == "FULL_TIME"
    assert job.description == "Shape the future.\n- Lead client projects"
    assert job.raw["job_id"] == "T7760115"
    assert job.raw["catalog_pass"] == 1
    assert job.raw["total_available"] == 2
    assert result.jobs[1].location == "Genève"


def test_bearingpoint_retries_until_catalog_and_feeds_converge() -> None:
    records = official_records()
    english_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal english_requests
        if request.url.path == "/jobs.json":
            return httpx.Response(
                200, json=feed_payload(records, locale="de"), request=request
            )
        if request.url.path == "/en/jobs.json":
            english_requests += 1
            selected = records[:1] if english_requests == 1 else records
            return httpx.Response(
                200, json=feed_payload(selected, locale="en"), request=request
            )
        return httpx.Response(200, text=listing_html(records), request=request)

    result = BearingpointSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 2
    assert result.message.endswith("2 catalog pass(es) across 6 requests")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item["_jobposting"]["jobLocation"][0]["address"].update(  # type: ignore[index,union-attr]
            {"addressCountry": "DE"}
        ),
        lambda item: item["_jobposting"]["hiringOrganization"].update(  # type: ignore[index,union-attr]
            {"sameAs": "https://evil.example"}
        ),
        lambda item: item.update(
            {"url": "https://evil.example/jobs/7760115-consultant"}
        ),
    ],
)
def test_bearingpoint_rejects_untrusted_feed_items(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    records = official_records()[:1]
    payload = feed_payload(records, locale="de")
    mutate(payload["items"][0])  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=payload, request=request)
        if request.url.path == "/en/jobs.json":
            return httpx.Response(
                200, json=feed_payload(records, locale="en"), request=request
            )
        return httpx.Response(200, text=listing_html(records), request=request)

    with pytest.raises(DirectCompanyRequestError, match="out-of-scope"):
        BearingpointSwitzerlandJobsParser(
            transport=httpx.MockTransport(handler)
        ).search(LinkedInSearchRequest())


def test_bearingpoint_rejects_duplicates_and_oversized_catalogs() -> None:
    records = official_records()
    duplicate = records[:1] + records[:1]
    duplicate_parser = BearingpointSwitzerlandJobsParser(
        transport=httpx.MockTransport(response_handler(duplicate))
    )
    oversized_parser = BearingpointSwitzerlandJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(response_handler(records)),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate_parser.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized_parser.search(LinkedInSearchRequest())


def test_bearingpoint_rejects_duplicate_ids_across_locale_feeds() -> None:
    records = official_records()[:1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jobs.json"):
            payload = feed_payload(records, locale="de")
            if request.url.path.startswith("/en/"):
                payload["home_page_url"] = (
                    "https://bearingpointag.teamtailor.com/en/jobs"
                )
                payload["feed_url"] = (
                    "https://bearingpointag.teamtailor.com/en/jobs.json"
                )
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(200, text=listing_html(records), request=request)

    with pytest.raises(DirectCompanyRequestError, match="locale feeds contain duplicate"):
        BearingpointSwitzerlandJobsParser(
            transport=httpx.MockTransport(handler)
        ).search(LinkedInSearchRequest())


def test_bearingpoint_rejects_persistent_catalog_mismatch() -> None:
    records = official_records()
    incomplete = records[:1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs.json":
            return httpx.Response(
                200, json=feed_payload(incomplete, locale="de"), request=request
            )
        if request.url.path == "/en/jobs.json":
            return httpx.Response(
                200, json=feed_payload(incomplete, locale="en"), request=request
            )
        return httpx.Response(200, text=listing_html(records), request=request)

    parser = BearingpointSwitzerlandJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="did not converge"):
        parser.search(LinkedInSearchRequest())


def test_bearingpoint_wraps_request_failures() -> None:
    parser = BearingpointSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bearingpoint_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["bearingpoint_switzerland"]

    assert isinstance(parser, BearingpointSwitzerlandJobsParser)
    assert parser.base_url == settings.bearingpoint_switzerland_jobs_base_url
    assert parser.feed_urls == (
        settings.bearingpoint_switzerland_jobs_feed_url_de,
        settings.bearingpoint_switzerland_jobs_feed_url_en,
    )
    assert parser.max_jobs == settings.bearingpoint_switzerland_jobs_max_jobs
    assert (
        parser.max_catalog_passes
        == settings.bearingpoint_switzerland_jobs_max_catalog_passes
    )
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "BearingPoint", "filters": {}},
            "sources": ["bearingpoint_switzerland", "bearingpoint_switzerland"],
        }
    )
    assert request.sources == ["bearingpoint_switzerland"]


def test_bearingpoint_jobs_render_as_direct_company_imports() -> None:
    record = {
        "job_id": "T7760115",
        "title": "Senior Consultant Operations",
        "company": "BearingPoint AG",
        "location": "Zürich",
        "public_url": (
            "https://www.bearingpoint.com/de-ch/karriere/stellenangebote/agebote/"
            "?id=T7760115&country=CH"
        ),
        "apply_url": (
            "https://bearingpointag.teamtailor.com/jobs/7760115-consultant/"
            "applications/new"
        ),
        "posted_at": "2026-05-19T09:30:00+02:00",
        "description": "Consulting role",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="bearingpoint_switzerland-T7760115",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "BearingPoint Switzerland import"
    assert stored["company"] == "BearingPoint AG"
    assert stored["id"] == "bearingpoint_switzerland-T7760115"
