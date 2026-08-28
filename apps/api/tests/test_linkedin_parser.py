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


def test_linkedin_parser_builds_batched_keyword_discovery_inputs() -> None:
    request = LinkedInSearchRequest.model_validate(
        {
            "keywords": "Entry IT",
            "location": "Switzerland",
            "country": "CH",
            "date_posted": "Past week",
            "remote": "Remote only",
            "linkedin_queries": [
                {
                    "keyword": "software engineer",
                    "experience_levels": ["Entry level", "Internship"],
                },
                {
                    "keyword": "working student IT",
                    "experience_levels": [],
                    "job_type": "Part-time",
                },
            ],
        }
    )

    inputs = LinkedInJobsParser.build_discovery_inputs(request)

    assert inputs == [
        {
            "location": "Switzerland",
            "keyword": "software engineer",
            "selective_search": True,
            "country": "CH",
            "time_range": "Past week",
            "experience_level": "Entry level",
            "remote": "Remote",
        },
        {
            "location": "Switzerland",
            "keyword": "software engineer",
            "selective_search": True,
            "country": "CH",
            "time_range": "Past week",
            "experience_level": "Internship",
            "remote": "Remote",
        },
        {
            "location": "Switzerland",
            "keyword": "working student IT",
            "selective_search": True,
            "country": "CH",
            "time_range": "Past week",
            "job_type": "Part-time",
            "remote": "Remote",
        },
    ]


def test_linkedin_discovery_maps_internship_job_type_to_experience_level() -> None:
    request = LinkedInSearchRequest.model_validate(
        {
            "keywords": "Entry IT",
            "location": "Switzerland",
            "country": "CH",
            "linkedin_queries": [
                {
                    "keyword": "IT",
                    "experience_levels": [],
                    "job_type": "Internship",
                },
                {
                    "keyword": "ICT",
                    "experience_levels": [],
                    "job_type": "Internship",
                },
            ],
        }
    )

    inputs = LinkedInJobsParser.build_discovery_inputs(request)

    assert inputs == [
        {
            "location": "Switzerland",
            "keyword": "IT",
            "selective_search": True,
            "country": "CH",
            "experience_level": "Internship",
        },
        {
            "location": "Switzerland",
            "keyword": "ICT",
            "selective_search": True,
            "country": "CH",
            "experience_level": "Internship",
        },
    ]


def test_linkedin_search_uses_async_keyword_discovery_and_upstream_limits(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured.update(url=url, **kwargs)
            return httpx.Response(
                200,
                json={"snapshot_id": "snapshot-123"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)
    parser = LinkedInJobsParser(api_key="key", api_url="https://api.example.test")

    response = parser.search(
        LinkedInSearchRequest(
            keywords="software engineer",
            location="Switzerland",
            country="Switzerland",
            results_limit=200,
            limit_per_input=10,
        )
    )

    assert captured["url"] == "https://api.example.test/trigger"
    assert captured["params"] == {
        "dataset_id": "gd_lpfll7v5hcqtkxl6l",
        "type": "discover_new",
        "discover_by": "keyword",
        "format": "json",
        "include_errors": "true",
        "limit_per_input": 10,
        "limit_multiple_results": 200,
    }
    assert captured["json"] == [
        {
            "location": "Switzerland",
            "keyword": "software engineer",
            "selective_search": True,
            "country": "CH",
        }
    ]
    assert response.status == "queued"
    assert response.snapshot_id == "snapshot-123"


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


def test_linkedin_snapshot_deduplicates_job_id_across_url_variants(monkeypatch) -> None:
    parser = LinkedInJobsParser(api_key="key", api_url="https://api.example.test")

    monkeypatch.setattr(parser, "get_snapshot_progress", lambda snapshot_id: {"status": "ready"})
    monkeypatch.setattr(
        parser,
        "download_snapshot",
        lambda snapshot_id: [
            {
                "job_posting_id": "4385163817",
                "job_title": "Junior Software Engineer",
                "url": "https://www.linkedin.com/jobs/view/junior-software-engineer-4385163817?_l=en",
            },
            {
                "job_title": "Junior Software Engineer",
                "url": "https://www.linkedin.com/jobs/view/4385163817?trackingId=abc",
            },
            {"error": "temporary discovery error"},
        ],
    )

    response = parser.get_snapshot("snapshot-123", results_limit=10, deduplicate=True)

    assert len(response.jobs) == 1
    assert response.jobs[0].title == "Junior Software Engineer"


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
