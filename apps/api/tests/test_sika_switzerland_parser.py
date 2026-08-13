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
from app.services.parsers.companies.sika_switzerland import (
    SikaSwitzerlandJobsParser,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

JOB_IDS = (
    "9c76864a-9d47-46eb-af82-10893fcfc91e",
    "f8c274e8-611d-4253-9602-49e5c5a31e35",
    "bfefbf0c-3d35-4ba1-a6f6-aac1eac03c15",
)


def job_url(index: int) -> str:
    return f"https://www.sika.test/en/career/jobs/job-posting-page/jid-{JOB_IDS[index]}.html"


def listing_payload(
    indexes: list[int],
    *,
    total: int,
    next_offset: int | None,
    country: str = "Switzerland",
) -> dict[str, object]:
    return {
        "filters": [],
        "items": [
            {
                "title": f"Technical Consultant {index}",
                "description": f"Listing summary for vacancy {index}.",
                "url": job_url(index),
                "imageUrl": None,
                "image": None,
                "id": JOB_IDS[index],
                "location": f"Zürich, Zurich, {country}",
                "tags": ["Full-time", "IT"],
                "label": "New" if index == 0 else None,
            }
            for index in indexes
        ],
        "totalItems": total,
        "nextOffset": next_offset,
        "limit": 20,
        "layout": "cardView",
        "query": None,
    }


def detail_html(
    index: int,
    *,
    country: str = "ch",
    title: str | None = None,
    identifier: str | None = None,
) -> str:
    schema = {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "title": title or f"Technical Consultant {index}",
        "description": "Build integration platforms.",
        "identifier": {
            "@type": "PropertyValue",
            "name": "JobId",
            "value": identifier or JOB_IDS[index],
        },
        "hiringOrganization": {"@type": "Organization", "name": "SIKA"},
        "industry": "Chemicals",
        "employmentType": "Full-time",
        "datePosted": "2026-07-09",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Zürich",
                "addressRegion": "Zurich",
                "addressCountry": country,
            },
        },
        "experienceRequirements": "Mid-Senior Level",
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(schema)}</script>
      <a class="cmp-button button primary"
         href="https://jobs.smartrecruiters.com/SikaAG/744000139193809-technical-consultant?oga=true">
        Apply Now
      </a>
      <div class="cmp-job-posting-details">
        <div class="cmp-job-posting-details__description">
          <p>Build integration platforms.</p>
          <ul><li>Operate APIs.</li></ul>
        </div>
        <div class="cmp-job-posting-details__qualifications">
          <ul><li>Eight years of experience.</li></ul>
        </div>
        <div class="cmp-job-posting-details__additional-information">
          <p>Flexible work options.</p>
        </div>
        <div class="cmp-job-posting-details__company-description">
          <p>Sika develops specialty chemicals.</p>
        </div>
      </div>
    </body></html>
    """


def test_sika_collects_every_swiss_page_and_enriches_details() -> None:
    requests: list[tuple[str, int | str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jobposting.listing.json"):
            assert request.url.params["country"] == "ch"
            offset = int(request.url.params["offset"])
            requests.append(("listing", offset))
            if offset == 0:
                return httpx.Response(
                    200,
                    json=listing_payload([0, 1], total=3, next_offset=2),
                    request=request,
                )
            return httpx.Response(
                200,
                json=listing_payload([2], total=3, next_offset=None),
                request=request,
            )
        job_id = request.url.path.removesuffix(".html").rsplit("jid-", 1)[-1]
        index = JOB_IDS.index(job_id)
        requests.append(("detail", index))
        return httpx.Response(200, text=detail_html(index), request=request)

    result = SikaSwitzerlandJobsParser(
        base_url="https://www.sika.test/en/career/jobs.html",
        catalog_url=(
            "https://www.sika.test/en/career/jobs/_jcr_content/content/"
            "layout/first/jobposting.listing.json"
        ),
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requests == [
        ("listing", 0),
        ("listing", 2),
        ("detail", 0),
        ("detail", 1),
        ("detail", 2),
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Sika Switzerland vacancies from 3 catalog records across 2 API requests"
    )
    assert len(result.jobs) == 3

    job = result.jobs[0]
    assert job.source == "sika_switzerland"
    assert job.title == "Technical Consultant 0"
    assert job.company == "Sika AG"
    assert job.location == "Zürich, Zurich, Switzerland"
    assert job.url == job_url(0)
    assert job.apply_url == (
        "https://jobs.smartrecruiters.com/SikaAG/744000139193809-technical-consultant?oga=true"
    )
    assert job.posted_at == "2026-07-09"
    assert job.employment_type == "Full-time"
    assert job.seniority == "Mid-Senior Level"
    assert job.description == (
        "About the Role\nBuild integration platforms.\n- Operate APIs.\n\n"
        "Your Skills and Experience\n- Eight years of experience.\n\n"
        "Why Join Us\nFlexible work options.\n\n"
        "About Sika\nSika develops specialty chemicals."
    )
    assert job.raw["listing_offset"] == 0
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["schema"]["@type"] == "JobPosting"


def test_sika_repeats_shifted_pages_until_all_ids_are_seen() -> None:
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if not request.url.path.endswith("jobposting.listing.json"):
            job_id = request.url.path.removesuffix(".html").rsplit("jid-", 1)[-1]
            index = JOB_IDS.index(job_id)
            return httpx.Response(200, text=detail_html(index), request=request)
        offset = int(request.url.params["offset"])
        if offset == 0:
            first_page_calls += 1
            return httpx.Response(
                200,
                json=listing_payload([0, 1], total=3, next_offset=2),
                request=request,
            )
        indexes = [1] if first_page_calls == 1 else [2]
        return httpx.Response(
            200,
            json=listing_payload(indexes, total=3, next_offset=None),
            request=request,
        )

    result = SikaSwitzerlandJobsParser(
        base_url="https://www.sika.test/en/career/jobs.html",
        catalog_url="https://www.sika.test/path/jobposting.listing.json",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert first_page_calls == 2
    assert len(result.jobs) == 3
    assert result.message.endswith("across 4 API requests")


def test_sika_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("jobposting.listing.json"):
            return httpx.Response(
                200,
                json=listing_payload([0], total=1, next_offset=None),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        SikaSwitzerlandJobsParser(
            base_url="https://www.sika.test/en/career/jobs.html",
            catalog_url="https://www.sika.test/path/jobposting.listing.json",
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Technical Consultant 0"
    assert job.location == "Zürich, Zurich, Switzerland"
    assert job.apply_url == job_url(0)
    assert job.description == "Listing summary for vacancy 0."
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_sika_rejects_non_swiss_catalog_and_mismatched_detail() -> None:
    parser = SikaSwitzerlandJobsParser(
        base_url="https://www.sika.test/en/career/jobs.html",
        catalog_url="https://www.sika.test/path/jobposting.listing.json",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload([0], total=1, next_offset=None, country="Germany"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        parser.search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="different vacancy"):
        parse_detail_html(
            detail_html(0, identifier=JOB_IDS[1]),
            page_url=job_url(0),
            expected_job_id=JOB_IDS[0],
            expected_title="Technical Consultant 0",
            expected_location="Zürich, Zurich, Switzerland",
        )
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy data"):
        parse_detail_html(
            detail_html(0, country="de"),
            page_url=job_url(0),
            expected_job_id=JOB_IDS[0],
            expected_title="Technical Consultant 0",
            expected_location="Zürich, Zurich, Switzerland",
        )


def test_sika_rejects_malformed_or_oversized_catalog() -> None:
    malformed = SikaSwitzerlandJobsParser(
        catalog_url="https://www.sika.test/path/jobposting.listing.json",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"totalItems": 1, "items": "invalid", "nextOffset": None},
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="invalid items"):
        malformed.search(LinkedInSearchRequest())

    oversized = SikaSwitzerlandJobsParser(
        catalog_url="https://www.sika.test/path/jobposting.listing.json",
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload([0, 1], total=3, next_offset=2),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="limit of 1 pages"):
        oversized.search(LinkedInSearchRequest())


def test_sika_wraps_listing_request_failures() -> None:
    parser = SikaSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_sika_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["sika_switzerland"]
    assert isinstance(parser, SikaSwitzerlandJobsParser)
    assert parser.base_url == settings.sika_switzerland_jobs_base_url
    assert parser.catalog_url == settings.sika_switzerland_jobs_catalog_url
    assert parser.max_pages == settings.sika_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == settings.sika_switzerland_jobs_max_catalog_passes
    assert parser.detail_workers == settings.sika_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Sika Switzerland", "filters": {}},
            "sources": ["sika_switzerland", "sika_switzerland"],
        }
    )
    assert request.sources == ["sika_switzerland"]


def test_sika_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": JOB_IDS[0],
        "title": "Technical Consultant 0",
        "description": "Build integration platforms.",
        "location": "Zürich, Zurich, Switzerland",
        "url": job_url(0),
        "tags": ["Full-time", "IT"],
        "detail": {
            "title": "Technical Consultant 0",
            "apply_url": (
                "https://jobs.smartrecruiters.com/SikaAG/"
                "744000139193809-technical-consultant?oga=true"
            ),
            "posted_at": "2026-07-09",
            "employment_type": "Full-time",
            "seniority": "Mid-Senior Level",
            "description": "Build integration platforms.",
        },
    }
    job = SikaSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"sika_switzerland-{JOB_IDS[0]}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Sika Switzerland import"
    assert stored["id"] == f"sika_switzerland-{JOB_IDS[0]}"
