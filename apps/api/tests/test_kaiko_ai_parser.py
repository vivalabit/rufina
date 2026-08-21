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
from app.services.parsers.companies.kaiko_ai import (
    KaikoAiJobsParser,
    normalize_job,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

FEED_URL = "https://jobs.kaiko.ai/jobs.json?location=Z%C3%BCrich"
JOB_ONE = "8212912"
JOB_TWO = "8086622"


def job_url(job_id: str, slug: str) -> str:
    return f"https://jobs.kaiko.ai/jobs/{job_id}-{slug}"


def schema_fixture(
    *,
    job_id: str,
    title: str,
    description: str,
    locations: list[tuple[str, str]],
    company: str = "kaiko.ai",
    employment_type: str | None = "FULL_TIME",
) -> dict[str, object]:
    schema: dict[str, object] = {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": int(job_id),
        },
        "datePosted": "2026-08-12T16:55:09+02:00",
        "hiringOrganization": {
            "@type": "Organization",
            "name": company,
            "sameAs": "https://jobs.kaiko.ai",
        },
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": locality,
                    "addressCountry": country,
                },
            }
            for locality, country in locations
        ],
    }
    if employment_type:
        schema["employmentType"] = employment_type
    return schema


def feed_item(
    *,
    feed_id: str,
    job_id: str,
    slug: str,
    title: str,
    locations: list[tuple[str, str]] | None = None,
    company: str = "kaiko.ai",
    employment_type: str | None = "FULL_TIME",
) -> dict[str, object]:
    description = (
        "<h2>About the role</h2><p>Build reliable clinical AI systems.</p>"
        "<ul><li>Ship production services.</li></ul>"
    )
    schema = schema_fixture(
        job_id=job_id,
        title=title,
        description=description,
        locations=locations or [("Amsterdam", "NL"), ("Zürich", "CH")],
        company=company,
        employment_type=employment_type,
    )
    return {
        "id": feed_id,
        "title": title,
        "url": job_url(job_id, slug),
        "date_published": schema["datePosted"],
        "content_html": description,
        "_jobposting": schema,
    }


def feed_payload(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "kaiko.ai",
        "home_page_url": "https://jobs.kaiko.ai/jobs",
        "feed_url": "https://jobs.kaiko.ai/jobs.json",
        "items": items,
    }


def detail_html(
    *,
    job_id: str,
    slug: str,
    title: str,
    company: str = "kaiko.ai",
    locations: list[tuple[str, str]] | None = None,
    visible_locations: str = "Amsterdam, Zürich",
    apply_url: str | None = None,
) -> str:
    public_url = job_url(job_id, slug)
    schema = schema_fixture(
        job_id=job_id,
        title=title,
        description="<p>Build reliable clinical AI systems.</p>",
        locations=locations or [("Amsterdam", "NL"), ("Zürich", "CH")],
        company=company,
    )
    application_url = apply_url or f"{public_url}/applications/new"
    return f"""
    <html><head>
      <meta property="og:url" content="{public_url}">
      <script type="application/ld+json">{json.dumps(schema)}</script>
    </head><body>
      <main data-careersite--jobs--form-overlay-job-application-url-value="{application_url}">
        <section><dl>
          <dt>Department</dt><dd>Engineering</dd>
          <dt>Locations</dt><dd>{visible_locations}</dd>
          <dt>Remote status</dt><dd>Hybrid</dd>
        </dl></section>
      </main>
    </body></html>
    """


def catalog_fixture() -> list[dict[str, object]]:
    return [
        feed_item(
            feed_id="cb448601-9f85-47a2-9e3a-e915ecc470e4",
            job_id=JOB_ONE,
            slug="partnerships-lead-api-partnerships",
            title="Partnerships Lead, API Partnerships",
        ),
        feed_item(
            feed_id="8ebd76af-008d-4cd4-a60c-b1821e44ef6d",
            job_id=JOB_TWO,
            slug="senior-backend-engineer",
            title="Senior Backend Engineer",
        ),
    ]


def test_kaiko_ai_collects_complete_zurich_feed_and_enriches_details() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/jobs.json":
            return httpx.Response(200, json=feed_payload(catalog_fixture()), request=request)
        if request.url.path.startswith(f"/jobs/{JOB_ONE}-"):
            return httpx.Response(
                200,
                text=detail_html(
                    job_id=JOB_ONE,
                    slug="partnerships-lead-api-partnerships",
                    title="Partnerships Lead, API Partnerships",
                ),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                job_id=JOB_TWO,
                slug="senior-backend-engineer",
                title="Senior Backend Engineer",
            ),
            request=request,
        )

    result = KaikoAiJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/jobs.json",
        f"/jobs/{JOB_ONE}-partnerships-lead-api-partnerships",
        f"/jobs/{JOB_TWO}-senior-backend-engineer",
    ]
    assert result.message == (
        "Scanned 2 kaiko.ai Zürich vacancies from the complete official Teamtailor JSON Feed"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "kaiko_ai"
    assert first.title == "Partnerships Lead, API Partnerships"
    assert first.company == "kaiko.ai"
    assert first.location == "Zürich, Switzerland"
    assert first.url == job_url(JOB_ONE, "partnerships-lead-api-partnerships")
    assert first.apply_url == f"{first.url}/applications/new"
    assert first.posted_at == "2026-08-12T16:55:09+02:00"
    assert first.employment_type == "Full-time"
    assert first.description and "- Ship production services" in first.description
    assert first.raw["all_locations"] == [
        {"locality": "Amsterdam", "country": "NL", "postal_code": None},
        {"locality": "Zürich", "country": "CH", "postal_code": None},
    ]
    assert first.raw["detail"]["remote_status"] == "Hybrid"
    assert first.raw["detail"]["employment_type"] == "Full-time"
    assert result.jobs[1].seniority == "Senior"


def test_kaiko_ai_preserves_verified_feed_record_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs.json":
            return httpx.Response(
                200,
                json=feed_payload([catalog_fixture()[0]]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        KaikoAiJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Partnerships Lead, API Partnerships"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description and "Build reliable clinical AI systems" in job.description
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "payload is invalid"),
        ({"items": []}, "invalid identity"),
        (
            feed_payload(
                [
                    feed_item(
                        feed_id="cb448601-9f85-47a2-9e3a-e915ecc470e4",
                        job_id=JOB_ONE,
                        slug="partnerships-lead-api-partnerships",
                        title="Partnerships Lead, API Partnerships",
                        company="Attacker AG",
                    )
                ]
            ),
            "non-Zürich vacancy",
        ),
        (
            feed_payload(
                [
                    feed_item(
                        feed_id="cb448601-9f85-47a2-9e3a-e915ecc470e4",
                        job_id=JOB_ONE,
                        slug="partnerships-lead-api-partnerships",
                        title="Partnerships Lead, API Partnerships",
                        locations=[("Amsterdam", "NL")],
                    )
                ]
            ),
            "non-Zürich vacancy",
        ),
    ],
)
def test_kaiko_ai_rejects_invalid_or_out_of_scope_feed(
    payload: object,
    message: str,
) -> None:
    parser = KaikoAiJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_kaiko_ai_rejects_duplicate_feed_and_configured_overflow() -> None:
    item = catalog_fixture()[0]

    def run(items: list[dict[str, object]], *, max_jobs: int = 100) -> None:
        KaikoAiJobsParser(
            max_jobs=max_jobs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=feed_payload(items),
                    request=request,
                )
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        run([item, item])
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        run(catalog_fixture(), max_jobs=1)


def test_kaiko_ai_accepts_a_verified_empty_feed() -> None:
    result = KaikoAiJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=feed_payload([]),
                request=request,
            )
        )
    ).search(LinkedInSearchRequest())

    assert result.status == "completed"
    assert result.jobs == []


def test_kaiko_ai_rejects_untrusted_detail() -> None:
    with pytest.raises(DirectCompanyRequestError, match="invalid identity"):
        parse_detail_html(
            detail_html(
                job_id=JOB_ONE,
                slug="partnerships-lead-api-partnerships",
                title="Partnerships Lead, API Partnerships",
                company="Attacker AG",
                apply_url="https://attacker.example/apply",
            ),
            page_url=job_url(JOB_ONE, "partnerships-lead-api-partnerships"),
            expected_url=job_url(JOB_ONE, "partnerships-lead-api-partnerships"),
            expected_job_id=JOB_ONE,
            expected_title="Partnerships Lead, API Partnerships",
        )


def test_kaiko_ai_wraps_feed_request_failures() -> None:
    parser = KaikoAiJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_kaiko_ai_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["kaiko_ai"]
    assert isinstance(parser, KaikoAiJobsParser)
    assert parser.base_url == settings.kaiko_ai_jobs_base_url
    assert parser.feed_url == settings.kaiko_ai_jobs_feed_url
    assert parser.max_jobs == settings.kaiko_ai_jobs_max_jobs
    assert parser.detail_workers == settings.kaiko_ai_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "kaiko.ai Zürich", "filters": {}},
            "sources": ["kaiko_ai", "kaiko_ai"],
        }
    )
    assert request.sources == ["kaiko_ai"]


def test_kaiko_ai_jobs_render_as_direct_company_imports() -> None:
    job = normalize_job(
        {
            "id": JOB_TWO,
            "title": "Senior Backend Engineer",
            "company": "kaiko.ai",
            "location": "Zürich, Switzerland",
            "url": job_url(JOB_TWO, "senior-backend-engineer"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"kaiko_ai-{JOB_TWO}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "kaiko.ai Zürich import"
    assert stored["id"] == f"kaiko_ai-{JOB_TWO}"
