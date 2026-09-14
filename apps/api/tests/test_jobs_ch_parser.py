import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import parsers as parsers_api
from app.main import app
from app.models.parsers import JobsChSearchRequest
from app.services.parsers import jobs_ch as jobs_ch_module
from app.services.parsers.jobs_ch import (
    JobsChParser,
    JobsChRequestError,
    extract_job_posting_schema,
    extract_js_object,
    extract_salary_info,
    extract_seniority,
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
    return f"<script>window.__INIT__ = {json.dumps(payload)};</script>"


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


def test_jobs_ch_searches_each_or_term_separately_and_deduplicates() -> None:
    requested_terms: list[str] = []
    detail_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            term = request.url.params["term"]
            requested_terms.append(term)
            rows = {
                "Lager": [
                    {"id": "shared", "title": "Shared job"},
                    {"id": "lager", "title": "Lager job"},
                ],
                "Logistik": [
                    {"id": "shared", "title": "Shared job"},
                    {"id": "logistik", "title": "Logistik job"},
                ],
                "Produktion": [{"id": "produktion", "title": "Produktion job"}],
            }[term]
            return httpx.Response(200, text=search_html(*rows))
        if request.url.path.startswith("/en/vacancies/detail/"):
            vacancy_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
            detail_ids.append(vacancy_id)
            return httpx.Response(503)
        return httpx.Response(404)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=1,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    response = parser.search(
        JobsChSearchRequest(
            keywords="Lager OR Logistik or Produktion OR lager",
            results_limit=10,
        )
    )

    assert requested_terms == ["Lager", "Logistik", "Produktion"]
    assert "OR" not in " ".join(requested_terms)
    assert [job.raw["id"] for job in response.jobs] == [
        "shared",
        "logistik",
        "produktion",
        "lager",
    ]
    assert sorted(detail_ids) == ["lager", "logistik", "produktion", "shared"]
    assert response.search_url == "https://jobs.example.test/en/vacancies/?term=Lager"


def test_jobs_ch_stops_pagination_when_first_pages_fill_limit() -> None:
    requested_pages: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            term = request.url.params["term"]
            page = int(request.url.params.get("page", "1"))
            requested_pages.append((term, page))
            return httpx.Response(
                200,
                text=search_html(
                    {"id": f"{term}-{page}", "title": f"{term} job"},
                    num_pages=10,
                ),
            )
        if request.url.path.startswith("/en/vacancies/detail/"):
            return httpx.Response(503)
        return httpx.Response(404)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    response = parser.search(
        JobsChSearchRequest(
            keywords="Lager OR Logistik OR Produktion OR Verpackung",
            results_limit=3,
        )
    )

    assert sorted(requested_pages) == [
        ("Lager", 1),
        ("Logistik", 1),
        ("Produktion", 1),
        ("Verpackung", 1),
    ]
    assert [job.raw["id"] for job in response.jobs] == [
        "Lager-1",
        "Logistik-1",
        "Produktion-1",
    ]


def test_jobs_ch_normalizes_broken_apply_suffix_only_for_jobs_ch() -> None:
    assert (
        normalize_jobs_ch_url("https://www.jobs.ch/en/vacancies/detail/vac-1/apply/")
        == "https://www.jobs.ch/en/vacancies/detail/vac-1/"
    )
    assert (
        normalize_jobs_ch_url("https://jobs.ch/en/vacancies/detail/vac-1/apply?source=test#form")
        == "https://jobs.ch/en/vacancies/detail/vac-1/?source=test#form"
    )
    assert (
        normalize_jobs_ch_url("https://employer.example/jobs/vac-1/apply")
        == "https://employer.example/jobs/vac-1/apply"
    )


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
    requested_details: list[str] = []

    def detail_html(date_posted: str, vacancy_id: str) -> str:
        return DETAIL_HTML.replace("2026-07-20T06:06:18+02:00", date_posted).replace(
            "vac-1", vacancy_id
        )

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
            requested_details.append("fresh")
            return httpx.Response(200, text=detail_html(fresh_date, "fresh"))
        if request.url.path == "/en/vacancies/detail/old/":
            requested_details.append("old")
            return httpx.Response(200, text=detail_html(old_date, "old"))
        if request.url.path == "/en/vacancies/detail/relisted/":
            requested_details.append("relisted")
            return httpx.Response(200, text=detail_html(fresh_date, "relisted"))
        return httpx.Response(404)

    parser = JobsChParser(
        base_url="https://jobs.example.test",
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )

    response = parser.search(JobsChSearchRequest(date_posted="Past 24 hours", results_limit=10))

    assert [job.raw["id"] for job in response.jobs] == ["fresh"]
    assert requested_details == ["fresh", "old"]


def test_jobs_ch_date_window_rejects_missing_invalid_and_future_dates() -> None:
    now = datetime(2026, 8, 23, 12, tzinfo=UTC)

    assert is_within_date_posted_window("2026-08-22T12:00:01+00:00", "Past 24 hours", now=now)
    assert not is_within_date_posted_window("2026-08-22T11:59:59+00:00", "Past 24 hours", now=now)
    assert not is_within_date_posted_window(None, "Past 24 hours", now=now)
    assert not is_within_date_posted_window("not-a-date", "Past 24 hours", now=now)
    assert not is_within_date_posted_window("2026-08-23T12:00:01+00:00", "Past 24 hours", now=now)


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
        "jobs.ch does not apply these filters: remote, experience level, job type, country"
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


def job_schema_html(vacancy_id: str, **overrides: object) -> str:
    schema = {
        "@type": "JobPosting",
        "title": vacancy_id,
        "url": f"https://www.jobs.ch/en/vacancies/detail/{vacancy_id}/",
        "description": "<p>Job description</p>",
        **overrides,
    }
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'


@pytest.mark.parametrize("fresh_on_next_page", [False, True])
def test_jobs_ch_refills_after_initial_date_filter(fresh_on_next_page: bool) -> None:
    fresh = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    stale_rows = [{"id": f"old-{i}", "initialPublicationDate": old} for i in range(2)]
    fresh_rows = [{"id": f"fresh-{i}", "initialPublicationDate": fresh} for i in range(2)]
    pages: list[int] = []
    details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            page = int(request.url.params.get("page", "1"))
            pages.append(page)
            rows = (
                (stale_rows if page == 1 else fresh_rows)
                if fresh_on_next_page
                else (stale_rows + fresh_rows)
            )
            return httpx.Response(200, text=search_html(*rows, num_pages=3))
        vacancy_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        details.append(vacancy_id)
        return httpx.Response(200, text=job_schema_html(vacancy_id))

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(date_posted="Past 24 hours", results_limit=2)
    )

    assert [job.raw["id"] for job in response.jobs] == ["fresh-0", "fresh-1"]
    assert sorted(details) == ["fresh-0", "fresh-1"]
    assert pages == ([1, 2] if fresh_on_next_page else [1])
    assert response.warnings == []


def test_jobs_ch_refills_after_detail_date_filter_and_url_deduplication() -> None:
    fresh = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    requested_details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            return httpx.Response(
                200,
                text=search_html(
                    {"id": "old"},
                    {"id": "fresh"},
                    {"id": "duplicate"},
                    {"id": "refill", "initialPublicationDate": "invalid-date"},
                ),
            )
        vacancy_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        requested_details.append(vacancy_id)
        schema_id = "fresh" if vacancy_id == "duplicate" else vacancy_id
        return httpx.Response(
            200, text=job_schema_html(schema_id, datePosted=old if vacancy_id == "old" else fresh)
        )

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(date_posted="Past 24 hours", results_limit=2)
    )

    assert [job.raw["id"] for job in response.jobs] == ["fresh", "refill"]
    assert sorted(requested_details) == ["duplicate", "fresh", "old", "refill"]
    assert response.warnings == []


@pytest.mark.parametrize("failure", ["or_term", "second_page"])
def test_jobs_ch_exposes_partial_listing_failure(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/en/vacancies/":
            return httpx.Response(200, text=job_schema_html("found"))
        if request.url.params.get("term") == "Java" or request.url.params.get("page") == "2":
            return httpx.Response(503)
        return httpx.Response(
            200, text=search_html({"id": "found"}, num_pages=2 if failure == "second_page" else 1)
        )

    response = JobsChParser(max_retries=0, transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(keywords="Python OR Java" if failure == "or_term" else "Python")
    )

    assert [job.raw["id"] for job in response.jobs] == ["found"]
    assert len(response.warnings) == 1
    assert "could not load page" in response.warnings[0]
    assert ("Java" if failure == "or_term" else "page 2") in response.warnings[0]
    assert response.message == response.warnings[0]


@pytest.mark.parametrize(
    "payload",
    [
        {"changed_structure": True},
        {"vacancy": {"results": {"main": {"results": None}}}},
        {"vacancy": {"results": {"main": {"results": [{"title": "No id"}]}}}},
    ],
)
def test_jobs_ch_rejects_malformed_search_structure(payload: dict[str, object]) -> None:
    parser = JobsChParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=f"<script>window.__INIT__ = {json.dumps(payload)};</script>"
            )
        )
    )

    with pytest.raises(JobsChRequestError):
        parser.search(JobsChSearchRequest())


def test_jobs_ch_empty_search_is_successful_and_unsupported_filters_are_not_degradation() -> None:
    parser = JobsChParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=search_html(num_pages=0))
        )
    )

    response = parser.search(JobsChSearchRequest(remote="Remote only"))

    assert response.jobs == []
    assert response.warnings == []
    assert response.message == "jobs.ch does not apply these filters: remote"


@pytest.mark.parametrize("detail_status", [200, 404, 503])
def test_jobs_ch_reports_incomplete_details_and_keeps_listing(detail_status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/en/vacancies/":
            return httpx.Response(200, text=search_html({"id": "found", "title": "Listing title"}))
        calls += 1
        return httpx.Response(detail_status, text="<html>No structured job</html>")

    response = JobsChParser(max_retries=0, transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest()
    )

    assert calls == 1
    assert response.jobs[0].title == "Listing title"
    assert len(response.warnings) == 1
    assert (
        "structured details were missing" if detail_status == 200 else "could not load details"
    ) in (response.warnings[0])


@pytest.mark.parametrize("failure", ["429", "503", "timeout"])
def test_jobs_ch_retries_transient_listing_errors(monkeypatch, failure: str) -> None:
    calls = 0
    delays: list[float] = []
    monkeypatch.setattr(jobs_ch_module, "sleep", delays.append)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("temporary", request=request)
            return httpx.Response(int(failure), headers={"Retry-After": "1"})
        return httpx.Response(200, text=search_html())

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(JobsChSearchRequest())

    assert calls == 2
    assert delays == ([0.25] if failure == "timeout" else [1.0])
    assert response.warnings == []


@pytest.mark.parametrize(
    ("status", "retry_after", "expected_calls"),
    [
        (404, None, 1),
        (429, "120", 1),
        (503, None, 3),
    ],
)
def test_jobs_ch_bounds_retries_and_respects_long_retry_after(
    monkeypatch, status: int, retry_after: str | None, expected_calls: int
) -> None:
    calls = 0
    monkeypatch.setattr(jobs_ch_module, "sleep", lambda seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Retry-After": retry_after} if retry_after else {})

    with pytest.raises(JobsChRequestError):
        JobsChParser(transport=httpx.MockTransport(handler)).search(JobsChSearchRequest())

    assert calls == expected_calls


def test_jobs_ch_deadline_stops_new_requests_and_retains_available_listing(monkeypatch) -> None:
    elapsed = [0.0]
    calls: list[str] = []
    monkeypatch.setattr(jobs_ch_module, "monotonic", lambda: elapsed[0])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.extensions["timeout"]["read"] <= 2.0
        elapsed[0] = 3.0
        return httpx.Response(
            200, text=search_html({"id": "found", "title": "Fallback"}, num_pages=2)
        )

    response = JobsChParser(deadline_seconds=2, transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest()
    )

    assert len(calls) == 1
    assert response.jobs[0].title == "Fallback"
    assert any("time limit" in warning for warning in response.warnings)
    assert any("could not load details" in warning for warning in response.warnings)


@pytest.mark.parametrize("missing_metadata", [False, True])
def test_jobs_ch_stops_repeating_pages_and_warns(missing_metadata: bool) -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/en/vacancies/":
            return httpx.Response(200, text=job_schema_html("found"))
        pages.append(int(request.url.params.get("page", "1")))
        page_html = search_html({"id": "found"}, num_pages=100)
        if missing_metadata:
            page_html = page_html.replace('"numPages": 100, ', "")
        return httpx.Response(200, text=page_html)

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(JobsChSearchRequest())

    assert pages == [1, 2]
    assert len(response.jobs) == 1
    assert any("repeated a page" in warning for warning in response.warnings)
    assert (
        any("pagination metadata" in warning for warning in response.warnings) == missing_metadata
    )


@pytest.mark.parametrize("results_limit", [1, 2])
def test_jobs_ch_warns_about_page_cap_only_if_more_results_are_needed(results_limit: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                search_html({"id": "found"}, num_pages=10)
                if request.url.path == "/en/vacancies/"
                else job_schema_html("found")
            ),
        )

    response = JobsChParser(max_pages=1, transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(results_limit=results_limit)
    )

    assert len(response.jobs) == 1
    assert bool(response.warnings) == (results_limit == 2)


def test_jobs_ch_uses_one_date_reference_for_the_whole_search(monkeypatch) -> None:
    reference = datetime(2026, 9, 14, 12, tzinfo=UTC)

    class MovingClock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return reference + timedelta(days=cls.calls - 1)

    monkeypatch.setattr(jobs_ch_module, "datetime", MovingClock)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            return httpx.Response(
                200,
                text=search_html(
                    {
                        "id": "fresh",
                        "initialPublicationDate": (reference - timedelta(hours=23)).isoformat(),
                    }
                ),
            )
        return httpx.Response(200, text=job_schema_html("fresh"))

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(date_posted="Past 24 hours")
    )

    assert len(response.jobs) == 1


def test_jobs_ch_extracts_graph_schema_and_numeric_experience() -> None:
    page_html = (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@graph": [
                    {"@type": "Organization"},
                    {
                        "@type": ["Thing", "JobPosting"],
                        "title": "Engineer",
                        "experienceRequirements": {"monthsOfExperience": 24},
                    },
                ],
            }
        )
        + "</script>"
    )

    schema = extract_job_posting_schema(page_html)

    assert schema is not None
    assert schema["title"] == "Engineer"
    assert extract_seniority(schema) == "24 months"


def test_jobs_ch_does_not_take_salary_from_unrelated_page_content() -> None:
    assert (
        extract_salary_info(
            "<aside>Other jobs earn CHF 90000 - 110000/year</aside>"
            '<script>const salary = "CHF 50000 - 60000/year";</script>'
        )
        is None
    )
    salary = extract_salary_info('<li data-cy="info-salary">CHF 5000 - 6000/month</li>')
    assert salary is not None
    assert salary["minimum"] == 5000
    assert salary["unit"] == "MONTH"


def test_jobs_ch_skips_malformed_normalized_job_and_refills() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/vacancies/":
            return httpx.Response(200, text=search_html({"id": "broken"}, {"id": "valid"}))
        vacancy_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            text=(
                job_schema_html(vacancy_id, url="https://[")
                if vacancy_id == "broken"
                else job_schema_html(vacancy_id)
            ),
        )

    response = JobsChParser(transport=httpx.MockTransport(handler)).search(
        JobsChSearchRequest(results_limit=1)
    )

    assert [job.raw["id"] for job in response.jobs] == ["valid"]
    assert any("malformed details" in warning for warning in response.warnings)
