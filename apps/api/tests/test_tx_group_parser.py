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
from app.services.parsers.companies.tx_group import TxGroupJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner


def listing_record(
    job_id: int,
    title: str,
    organization: str,
    host: str,
    *,
    language_prefix: str = "",
) -> dict[str, object]:
    slug = title.casefold().replace("&", "and").replace(" ", "-").replace("/", "-")
    return {
        "job_id": str(job_id),
        "title": title,
        "organization": organization,
        "public_url": f"https://{host}{language_prefix}/jobs/{job_id}-{slug}",
    }


def official_records() -> list[dict[str, object]]:
    return [
        listing_record(
            8172175,
            "Lehre als Kauffrau Kaufmann EFZ",
            "TX Group AG",
            "jobs.tx.group",
        ),
        listing_record(
            8190699,
            "Praktikum Redaktion Politik",
            "20 Minuten",
            "jobs.20minuten.ch",
        ),
        listing_record(
            8006148,
            "Specialist Retail B2B Customer Operations",
            "Tamedia",
            "jobs.tamedia.ch",
            language_prefix="/fr",
        ),
    ]


def listing_html(records: list[dict[str, object]]) -> str:
    links = "".join(
        f'<li><a href="{record["public_url"]}"><span></span>{record["title"]}</a></li>'
        for record in records
    )
    return f"""
    <html><body>
      <a data-test="company-logo">TX Group AG</a>
      <div><span>{len(records)} Jobs</span></div>
      <ul id="jobs_list_container">{links}</ul>
    </body></html>
    """


def feed_item(
    record: dict[str, object],
    index: int,
) -> dict[str, object]:
    job_id = int(record["job_id"])
    title = str(record["title"])
    organization = str(record["organization"])
    organization_urls = {
        "TX Group AG": "https://jobs.tx.group",
        "20 Minuten": "https://jobs.20minuten.ch",
        "Tamedia": "https://jobs.tamedia.ch",
    }
    description = "<p>Shape Swiss media.</p><ul><li>Lead digital projects</li></ul>"
    published_at = "2026-08-14T10:30:00+02:00"
    return {
        "id": f"00000000-0000-4000-8000-{index:012d}",
        "title": title,
        "url": f"https://jobs.tx.group/jobs/{job_id}-canonical-job",
        "date_published": published_at,
        "content_html": description,
        "_jobposting": {
            "@context": "http://schema.org/",
            "@type": "JobPosting",
            "title": title,
            "description": description,
            "identifier": {
                "@type": "PropertyValue",
                "name": organization,
                "value": job_id,
            },
            "datePosted": published_at,
            "employmentType": "FULL_TIME" if index == 1 else None,
            "hiringOrganization": {
                "@type": "Organization",
                "name": organization,
                "sameAs": organization_urls[organization],
            },
            "jobLocation": [
                {
                    "@type": "Place",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "Werdstrasse 21",
                        "addressLocality": "Zürich" if index < 3 else "Lausanne",
                        "postalCode": "8004",
                        "addressCountry": "CH",
                    },
                }
            ],
        },
    }


def feed_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "TX Group AG",
        "home_page_url": "https://jobs.tx.group/jobs",
        "feed_url": "https://jobs.tx.group/jobs.json",
        "items": [feed_item(record, index) for index, record in enumerate(records, 1)],
    }


def test_tx_group_scans_complete_multibrand_catalog() -> None:
    records = official_records()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=feed_payload(records), request=request)
        return httpx.Response(200, text=listing_html(records), request=request)

    result = TxGroupJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert len(requests) == 2
    assert requests[0].url.params["_"] == requests[1].url.params["_"]
    assert result.message == (
        "Scanned 3 TX Group vacancies from the complete official Teamtailor JSON Feed, "
        "reconciled in 1 catalog pass(es) across 2 requests"
    )
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "tx_group"
    assert first.title == "Lehre als Kauffrau Kaufmann EFZ"
    assert first.company == "TX Group AG"
    assert first.location == "Zürich"
    assert first.url == "https://jobs.tx.group/jobs/8172175-lehre-als-kauffrau-kaufmann-efz"
    assert first.apply_url == (
        "https://jobs.tx.group/jobs/8172175-lehre-als-kauffrau-kaufmann-efz/applications/new"
    )
    assert first.posted_at == "2026-08-14T10:30:00+02:00"
    assert first.employment_type == "FULL_TIME"
    assert first.description == "Shape Swiss media.\n- Lead digital projects"
    assert first.raw["catalog_pass"] == 1
    assert first.raw["total_available"] == 3
    assert result.jobs[1].company == "20 Minuten"
    assert result.jobs[2].url and result.jobs[2].url.startswith("https://jobs.tamedia.ch/fr/")


def test_tx_group_retries_until_html_and_feed_converge() -> None:
    records = official_records()
    feed_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal feed_requests
        if request.url.path == "/jobs.json":
            feed_requests += 1
            selected = records[:-1] if feed_requests == 1 else records
            return httpx.Response(200, json=feed_payload(selected), request=request)
        return httpx.Response(200, text=listing_html(records), request=request)

    result = TxGroupJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert result.message.endswith("reconciled in 2 catalog pass(es) across 4 requests")


def test_tx_group_retries_when_feed_is_ahead_of_html() -> None:
    records = official_records()
    listing_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_requests
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=feed_payload(records), request=request)
        listing_requests += 1
        selected = records[:-1] if listing_requests == 1 else records
        return httpx.Response(200, text=listing_html(selected), request=request)

    result = TxGroupJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert len(result.jobs) == 3
    assert result.message.endswith("reconciled in 2 catalog pass(es) across 4 requests")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda item: item["_jobposting"]["hiringOrganization"].update(  # type: ignore[index,union-attr]
                {"sameAs": "https://evil.example"}
            ),
            "out-of-scope",
        ),
        (
            lambda item: item["_jobposting"]["jobLocation"][0]["address"].update(  # type: ignore[index,union-attr]
                {"addressCountry": "DE"}
            ),
            "out-of-scope",
        ),
        (
            lambda item: item.update({"url": "https://evil.example/jobs/8172175-job"}),
            "out-of-scope",
        ),
    ],
)
def test_tx_group_rejects_untrusted_feed_items(
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    records = official_records()[:1]
    payload = feed_payload(records)
    item = payload["items"][0]  # type: ignore[index]
    mutate(item)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(200, text=listing_html(records), request=request)

    parser = TxGroupJobsParser(transport=httpx.MockTransport(handler))
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_tx_group_rejects_duplicate_and_oversized_catalogs() -> None:
    record = official_records()[0]
    duplicate_listing = TxGroupJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html([record, record]),
                request=request,
            )
        )
    )
    oversized = TxGroupJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(official_records()),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate_listing.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_tx_group_rejects_persistent_catalog_mismatch() -> None:
    records = official_records()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=feed_payload(records[:-1]), request=request)
        return httpx.Response(200, text=listing_html(records), request=request)

    parser = TxGroupJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="did not converge"):
        parser.search(LinkedInSearchRequest())


def test_tx_group_wraps_request_failures() -> None:
    parser = TxGroupJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_tx_group_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["tx_group"]

    assert isinstance(parser, TxGroupJobsParser)
    assert parser.base_url == settings.tx_group_jobs_base_url
    assert parser.feed_url == settings.tx_group_jobs_feed_url
    assert parser.max_jobs == settings.tx_group_jobs_max_jobs
    assert parser.max_catalog_passes == settings.tx_group_jobs_max_catalog_passes
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "TX Group", "filters": {}},
            "sources": ["tx_group", "tx_group"],
        }
    )
    assert request.sources == ["tx_group"]


def test_tx_group_jobs_render_as_direct_company_imports() -> None:
    record = {
        "job_id": "8172175",
        "title": "Lehre als Kauffrau Kaufmann EFZ",
        "company": "TX Group AG",
        "location": "Zürich",
        "public_url": "https://jobs.tx.group/jobs/8172175-job",
        "apply_url": "https://jobs.tx.group/jobs/8172175-job/applications/new",
        "posted_at": "2026-08-14T10:30:00+02:00",
        "description": "Apprenticeship",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="tx_group-8172175",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "TX Group AG import"
    assert stored["company"] == "TX Group AG"
