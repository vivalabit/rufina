from typing import Self

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app
from app.models.parsers import LinkedInSearchRequest
from app.services.parsers.linkedin import BrightDataRequestError, LinkedInJobsParser


def test_linkedin_parser_builds_search_url() -> None:
    request = LinkedInSearchRequest(
        keywords="Product Designer",
        location="Europe",
        remote="Remote only",
        experience_level="Mid-Senior level",
        job_type="Full-time",
        date_posted="Past week",
        results_limit=50,
    )

    url = LinkedInJobsParser.build_search_url(request)

    assert url.startswith("https://www.linkedin.com/jobs/search/?")
    assert "keywords=Product+Designer" in url
    assert "location=Europe" in url
    assert "f_WT=2" in url
    assert "f_E=4" in url
    assert "f_JT=F" in url
    assert "f_TPR=r604800" in url


def test_linkedin_parser_normalizes_job_record() -> None:
    job = LinkedInJobsParser.normalize_job(
        {
            "job_title": "Senior Product Designer",
            "company_name": "Stripe",
            "job_location": "Remote",
            "url": "https://www.linkedin.com/jobs/view/123",
            "apply_link": "https://www.linkedin.com/jobs/view/123/apply",
            "job_employment_type": "Full-time",
            "job_seniority_level": "Mid-Senior level",
            "job_summary": "Design payment products.",
        }
    )

    assert job.title == "Senior Product Designer"
    assert job.company == "Stripe"
    assert job.location == "Remote"
    assert job.apply_url == "https://www.linkedin.com/jobs/view/123/apply"
    assert job.raw["job_title"] == "Senior Product Designer"


def test_linkedin_search_reports_rejected_brightdata_key(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> httpx.Response:
            return httpx.Response(
                401,
                text="Invalid credentials",
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    parser = LinkedInJobsParser(api_key="expired-key", api_url="https://api.example.test")

    with pytest.raises(
        BrightDataRequestError,
        match=r"Bright Data API key was rejected\. Replace it in Settings\.",
    ):
        parser.search(LinkedInSearchRequest(keywords="Product Designer"))


def test_linkedin_snapshot_returns_queued_when_download_is_not_ready(monkeypatch) -> None:
    parser = LinkedInJobsParser(api_key="key", api_url="https://api.example.test")

    monkeypatch.setattr(parser, "get_snapshot_progress", lambda snapshot_id: {})
    monkeypatch.setattr(parser, "download_snapshot", lambda snapshot_id: None)

    response = parser.get_snapshot("snapshot-123")

    assert response.status == "queued"
    assert response.snapshot_id == "snapshot-123"
    assert response.jobs == []


def test_linkedin_snapshot_normalizes_downloaded_records(monkeypatch) -> None:
    parser = LinkedInJobsParser(api_key="key", api_url="https://api.example.test")

    monkeypatch.setattr(parser, "get_snapshot_progress", lambda snapshot_id: {"status": "ready"})
    monkeypatch.setattr(
        parser,
        "download_snapshot",
        lambda snapshot_id: [
            {
                "job_title": "Senior Product Designer",
                "company_name": "Stripe",
                "job_location": "Remote",
                "url": "https://www.linkedin.com/jobs/view/123",
            },
            {
                "job_title": "Senior Product Designer",
                "company_name": "Stripe",
                "job_location": "Remote",
                "url": "https://www.linkedin.com/jobs/view/123",
            },
        ],
    )

    response = parser.get_snapshot("snapshot-123", results_limit=10, deduplicate=True)

    assert response.status == "completed"
    assert response.snapshot_id == "snapshot-123"
    assert len(response.jobs) == 1
    assert response.jobs[0].title == "Senior Product Designer"


def test_linkedin_search_requires_brightdata_key(monkeypatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "")
    get_settings.cache_clear()
    client = TestClient(app)

    try:
        response = client.post(
            "/parsers/linkedin/search",
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
