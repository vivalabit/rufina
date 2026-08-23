import json
from datetime import UTC, datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from app.api import parsers as parsers_api
from app.main import app
from app.models.parsers import JobsChSearchRequest
from app.services.parsers.jobs_ch import (
    JobsChParser,
    JobsChRequestError,
    extract_job_posting_schema,
    extract_js_object,
    is_within_date_posted_window,
    normalize_jobs_ch_url,
)


def search_html(*rows: dict[str, object], num_pages: int = 1) -> str:
    payload = {
        "vacancy": {
            "results": {
                "main": {
                    "meta": {"numPages": num_pages, "baseOptions": {"rows": 20}},
                    "results": list(rows),
                }
            }
        }
    }
    return f'<script>window.__INIT__ = {json.dumps(payload)};</script>'


DETAIL_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {
        "@type": "JobPosting",
        "title": "Senior Platform Engineer",
        "description": "<p>Build Python services &amp; cloud platforms.</p>",
        "datePosted": "2026-07-20T06:06:18+02:00",
        "employmentType": "Permanent position",
        "hiringOrganization": {"@type": "Organization", "name": "Acme AG"},
        "jobLocation": {
          "@type": "Place",
          "address": {
            "@type": "PostalAddress",
            "postalCode": "8005",
            "addressRegion": "Zürich",
            "addressCountry": "CH"
          }
        },
        "url": "https://www.jobs.ch/en/vacancies/detail/vac-1/",
        "potentialAction": {
          "@type": "ApplyAction",
          "target": {
            "@type": "EntryPoint",
            "urlTemplate": "https://www.jobs.ch/en/vacancies/detail/vac-1/apply"
          }
        }
      }
    </script>
  </head>
  <body>
    <li data-cy="info-salary">CHF 105'000 - 125'000/year</li>
  </body>
</html>
"""


def test_jobs_ch_parser_builds_search_url() -> None:
    parser = JobsChParser()
    request = JobsChSearchRequest(keywords="Platform Engineer", location="Zürich")

    assert parser.build_search_url(request) == (
        "https://www.jobs.ch/en/vacancies/?term=Platform+Engineer&location=Z%C3%BCrich"
    )


def test_jobs_ch_parser_applies_publication_date_to_search_url() -> None:
    parser = JobsChParser()
    request = JobsChSearchRequest(
        keywords="Platform Engineer",
        date_posted="Past 24 hours",
    )

    assert parser.build_search_url(request) == (
        "https://www.jobs.ch/en/vacancies/?term=Platform+Engineer&publication-date=1"
    )


def test_jobs_ch_extracts_balanced_init_state() -> None:
    payload = extract_js_object(
        '<script>window.__INIT__ = {"message":"brace } in string","vacancy":{}};</script>',
        "__INIT__ =",
    )

    assert payload["message"] == "brace } in string"


def test_jobs_ch_extracts_job_posting_schema() -> None:
    schema = extract_job_posting_schema(DETAIL_HTML)

    assert schema is not None
    assert schema["title"] == "Senior Platform Engineer"


def test_jobs_ch_search_and_detail_normalize_job() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/en/vacancies/":
            return httpx.Response(
                200,
                text=search_html(
                    {
                        "id": "vac-1",
                        "title": "Platform Engineer",
                        "company": {"name": "Acme"},
                        "place": "Zürich",
                        "publicationDate": "2026-07-20T06:06:18+02:00",
                    }
                ),
            )
        if request.url.path == "/en/vacancies/detail/vac-1/":
            return httpx.Response(200, text=DETAIL_HTML)
        return httpx.Response(404)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )
    response = parser.search(
        JobsChSearchRequest(
            keywords="Platform Engineer",
            location="Zürich",
            results_limit=10,
        )
    )

    assert response.parser == "jobs_ch"
    assert response.status == "completed"
    assert response.search_url == (
        "https://jobs.example.test/en/vacancies/?term=Platform+Engineer&location=Z%C3%BCrich"
    )
    assert len(response.jobs) == 1
    job = response.jobs[0]
    assert job.source == "jobs_ch"
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Acme AG"
    assert job.location == "Zürich"
    assert job.employment_type == "Permanent position"
    assert job.description == "Build Python services & cloud platforms."
    assert job.apply_url == "https://www.jobs.ch/en/vacancies/detail/vac-1/"
    assert job.salary == "CHF 105000-125000 / year"
    assert job.salary_min == 105000
    assert job.salary_max == 125000
    assert job.salary_currency == "CHF"
    assert job.salary_unit == "YEAR"
    assert any("term=Platform+Engineer" in url for url in requested_urls)


def test_jobs_ch_normalizes_broken_apply_suffix_only_for_jobs_ch() -> None:
    assert normalize_jobs_ch_url(
        "https://www.jobs.ch/en/vacancies/detail/vac-1/apply/"
    ) == "https://www.jobs.ch/en/vacancies/detail/vac-1/"
    assert normalize_jobs_ch_url(
        "https://jobs.ch/en/vacancies/detail/vac-1/apply?source=test#form"
    ) == "https://jobs.ch/en/vacancies/detail/vac-1/?source=test#form"
    assert normalize_jobs_ch_url(
        "https://employer.example/jobs/vac-1/apply"
    ) == "https://employer.example/jobs/vac-1/apply"


def test_jobs_ch_keeps_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            return httpx.Response(
                200,
                text=search_html(
                    {
                        "id": "vac-2",
                        "title": "Data Engineer",
                        "company": {"name": "Beta AG"},
                        "place": "Bern",
                    }
                ),
            )
        return httpx.Response(503)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    response = parser.search(JobsChSearchRequest(keywords="Data Engineer"))

    assert len(response.jobs) == 1
    assert response.jobs[0].title == "Data Engineer"
    assert response.jobs[0].company == "Beta AG"
    assert response.jobs[0].raw["detail_error"]


def test_jobs_ch_strictly_excludes_results_older_than_24_hours() -> None:
    fresh_date = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    old_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    def detail_html(date_posted: str, vacancy_id: str) -> str:
        return DETAIL_HTML.replace(
            "2026-07-20T06:06:18+02:00", date_posted
        ).replace("vac-1", vacancy_id)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            assert request.url.params["publication-date"] == "1"
            return httpx.Response(
                200,
                text=search_html(
                    {"id": "fresh", "title": "Fresh job", "publicationDate": fresh_date},
                    {"id": "old", "title": "Old job", "publicationDate": old_date},
                    {
                        "id": "relisted",
                        "title": "Relisted old job",
                        "publicationDate": fresh_date,
                        "initialPublicationDate": old_date,
                    },
                ),
            )
        if request.url.path == "/en/vacancies/detail/fresh/":
            return httpx.Response(200, text=detail_html(fresh_date, "fresh"))
        if request.url.path == "/en/vacancies/detail/old/":
            return httpx.Response(200, text=detail_html(old_date, "old"))
        if request.url.path == "/en/vacancies/detail/relisted/":
            return httpx.Response(200, text=detail_html(fresh_date, "relisted"))
        return httpx.Response(404)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    response = parser.search(
        JobsChSearchRequest(date_posted="Past 24 hours", results_limit=10)
    )

    assert [job.raw["id"] for job in response.jobs] == ["fresh"]


def test_jobs_ch_date_window_rejects_missing_invalid_and_future_dates() -> None:
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)

    assert is_within_date_posted_window(
        "2026-08-22T12:00:01+00:00", "Past 24 hours", now=now
    )
    assert not is_within_date_posted_window(
        "2026-08-22T11:59:59+00:00", "Past 24 hours", now=now
    )
    assert not is_within_date_posted_window(None, "Past 24 hours", now=now)
    assert not is_within_date_posted_window("not-a-date", "Past 24 hours", now=now)
    assert not is_within_date_posted_window(
        "2026-08-23T12:00:01+00:00", "Past 24 hours", now=now
    )


def test_jobs_ch_reports_filters_not_supported_by_reference_parser() -> None:
    request = JobsChSearchRequest(
        remote="Remote only",
        experience_level="Director",
        job_type="Contract",
        date_posted="Past week",
        country="Germany",
    )

    message = JobsChParser.unsupported_filters_message(request)

    assert message == (
        "jobs.ch does not apply these filters: remote, experience level, job type, "
        "country"
    )


def test_jobs_ch_endpoint_maps_upstream_failure_to_bad_gateway(monkeypatch) -> None:
    class FailingParser:
        def search(self, request: JobsChSearchRequest) -> None:
            raise JobsChRequestError("jobs.ch search request failed")

    monkeypatch.setattr(parsers_api, "_jobs_ch_parser", lambda: FailingParser())

    response = TestClient(app).post(
        "/parsers/jobs_ch/search",
        json={"keywords": "Platform Engineer", "results_limit": 10},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "jobs.ch search request failed"
