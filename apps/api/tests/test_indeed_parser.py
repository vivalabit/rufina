from typing import Self

import httpx
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app
from app.models.parsers import IndeedSearchRequest
from app.services.parsers.indeed import INDEED_JOBS_DATASET_ID, IndeedJobsParser


def test_indeed_parser_builds_search_url() -> None:
    request = IndeedSearchRequest(
        keywords="Product Designer",
        location="Zurich",
        remote="Hybrid",
        experience_level="Mid-Senior level",
        job_type="Full-time",
        date_posted="Past week",
        results_limit=50,
        country="Switzerland",
    )

    url = IndeedJobsParser.build_search_url(request)

    assert url.startswith("https://ch.indeed.com/jobs?")
    assert "q=Product+Designer" in url
    assert "l=Zurich" in url
    assert "sc=0kf%3Aattr%28PAXZC%29%3B" in url
    assert "explvl=mid_level" in url
    assert "jt=fulltime" in url
    assert "fromage=7" in url


def test_indeed_parser_uses_country_as_location_fallback() -> None:
    request = IndeedSearchRequest(country="Germany")

    assert IndeedJobsParser.build_search_url(request) == "https://de.indeed.com/jobs?l=Germany"


def test_indeed_parser_normalizes_job_record() -> None:
    job = IndeedJobsParser.normalize_job(
        {
            "jobid": "f236970b0305e1c7",
            "job_title": "Research Scientist",
            "company_name": "Amentum",
            "location": "Remote",
            "date_posted_parsed": "2026-07-15T19:29:33.997Z",
            "job_type": "Full-time",
            "description_text": "Research signal processing systems.",
        }
    )

    assert job.source == "indeed"
    assert job.title == "Research Scientist"
    assert job.company == "Amentum"
    assert job.url == "https://www.indeed.com/viewjob?jk=f236970b0305e1c7"
    assert job.apply_url == job.url
    assert job.posted_at == "2026-07-15T19:29:33.997Z"
    assert job.description == "Research signal processing systems."


def test_indeed_parser_has_official_brightdata_dataset_default() -> None:
    parser = IndeedJobsParser(api_key="key", api_url="https://api.example.test")

    assert parser.dataset_id == INDEED_JOBS_DATASET_ID == "gd_l4dx9j9sscpvs7no2"


def test_indeed_search_calls_brightdata_async_trigger_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured["url"] = url
            captured.update(kwargs)
            return httpx.Response(
                200,
                json={"snapshot_id": "snapshot-indeed"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    parser = IndeedJobsParser(api_key="key", api_url="https://api.example.test")

    response = parser.search(IndeedSearchRequest(keywords="Research Scientist"))

    assert captured["url"] == "https://api.example.test/trigger"
    assert captured["params"] == {
        "dataset_id": INDEED_JOBS_DATASET_ID,
        "type": "discover_new",
        "discover_by": "url",
        "format": "json",
        "include_errors": "true",
    }
    assert captured["json"] == [
        {
            "url": "https://www.indeed.com/jobs?q=Research+Scientist",
        }
    ]
    assert response.status == "queued"
    assert response.snapshot_id == "snapshot-indeed"


def test_indeed_snapshot_normalizes_and_deduplicates_records(monkeypatch) -> None:
    parser = IndeedJobsParser(api_key="key", api_url="https://api.example.test")
    record = {
        "jobid": "f236970b0305e1c7",
        "job_title": "Research Scientist",
        "company_name": "Amentum",
    }

    monkeypatch.setattr(parser, "get_snapshot_progress", lambda snapshot_id: {"status": "ready"})
    monkeypatch.setattr(parser, "download_snapshot", lambda snapshot_id: [record, record])

    response = parser.get_snapshot("snapshot-indeed", results_limit=10, deduplicate=True)

    assert response.parser == "indeed"
    assert response.status == "completed"
    assert len(response.jobs) == 1
    assert response.jobs[0].source == "indeed"


def test_indeed_search_requires_brightdata_key(monkeypatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "")
    get_settings.cache_clear()
    client = TestClient(app)

    try:
        response = client.post(
            "/parsers/indeed/search",
            json={
                "keywords": "Product Designer",
                "location": "Europe",
                "remote": "Remote only",
                "experience_level": "Any",
                "job_type": "Any",
                "date_posted": "Any time",
                "results_limit": 10,
                "country": "Any",
                "deduplicate": True,
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "BRIGHTDATA_API_KEY is not configured"
