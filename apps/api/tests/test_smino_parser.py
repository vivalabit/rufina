from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.smino import SminoJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://smino.jobs.personio.com/"
LOGO_URL = "https://assets.cdn.personio.de/logos/89984/social/72241c86fdde4d186046d98f8f119afa.png"
JOB_IDS = ("2691240", "2756903", "2608241")
TITLES = (
    "Full Stack Engineer (AI-First) (m/w/d) 100%",
    "Product Designer (UI/UX) - 80% (m/w/d)",
    "Sales Manager B2B SaaS (alemán nativo)",
)
LOCATIONS = ("Zürich", "Zürich", "Barcelona (Remote)")
SCHEDULES = ("Vollzeit", "Teilzeit", "Vollzeit")


def listing_card(index: int, *, job_id: str | None = None) -> str:
    return f"""
      <a class="job-box" href="/job/{job_id or JOB_IDS[index]}">
        <h3>{TITLES[index]}</h3>
        <div class="jb-description">
          <span>{LOCATIONS[index]}</span>
          <span>{SCHEDULES[index]}</span>
          <span>Festanstellung</span>
        </div>
      </a>
    """


def listing_html(
    cards: list[str] | None = None,
    *,
    title: str = "Jobs bei smino AG",
    logo_url: str = LOGO_URL,
) -> str:
    content = "".join(
        [listing_card(0), listing_card(1), listing_card(2)] if cards is None else cards
    )
    return f"""
      <!doctype html>
      <html lang="en">
        <head>
          <title>{title}</title>
          <link rel="canonical" href="{BASE_URL}?language=de">
          <meta property="og:title" content="Jobs bei smino AG">
        </head>
        <body>
          <header><img src="{logo_url}" alt="smino AG"></header>
          <h1>Offene Stellen</h1>
          <div aria-label="Offene Positionen">{content}</div>
        </body>
      </html>
    """


def job_posting(index: int) -> dict[str, Any]:
    country = "CH" if index < 2 else "ES"
    locality = "Zürich" if index < 2 else "Barcelona"
    return {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": TITLES[index],
        "description": (
            "<h2>Deine Aufgaben</h2><p>Gestalte mit uns digitale Bauprozesse und "
            "entwickle verlässliche Lösungen für anspruchsvolle Kundinnen und Kunden "
            "in einem internationalen, produktorientierten Team.</p>"
            "<ul><li>Übernimm Verantwortung und liefere messbare Ergebnisse.</li></ul>"
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": "smino AG",
            "value": f"{JOB_IDS[index]}-89984",
        },
        "hiringOrganization": {
            "@type": "Organization",
            "name": "smino AG",
            "logo": LOGO_URL,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": locality,
                "addressCountry": country,
            },
        },
        "datePosted": ("2026-06-30", "2026-08-17", "2026-04-21")[index],
        "employmentType": "PART_TIME" if index == 1 else "FULL_TIME",
    }


def detail_html(index: int, *, posting: dict[str, Any] | None = None) -> str:
    payload = posting or job_posting(index)
    job_id = JOB_IDS[index]
    title = payload["title"]
    url = f"https://smino.jobs.personio.com/job/{job_id}?language=de"
    return f"""
      <!doctype html>
      <html lang="en">
        <head>
          <title>{title} | Jobs bei smino AG</title>
          <link rel="canonical" href="{url}">
          <meta property="og:title" content="{title} | Jobs bei smino AG">
        </head>
        <body>
          <script type="application/ld+json">{json.dumps(payload)}</script>
          <a href="/job/{job_id}/apply?language=de">Für diese Stelle bewerben</a>
        </body>
      </html>
    """


def parser_for(
    *,
    page: str | None = None,
    details: dict[str, str | int] | None = None,
    page_status: int = 200,
    **kwargs: Any,
) -> tuple[SminoJobsParser, list[str]]:
    requests: list[str] = []
    detail_values = details or {job_id: detail_html(index) for index, job_id in enumerate(JOB_IDS)}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/":
            return httpx.Response(page_status, text=page or listing_html(), request=request)
        job_id = request.url.path.rstrip("/").split("/")[-1]
        value = detail_values[job_id]
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        return httpx.Response(200, text=value, request=request)

    return (
        SminoJobsParser(
            base_url=BASE_URL,
            detail_workers=1,
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
        requests,
    )


def test_smino_scans_complete_catalog_and_enriches_personio_details() -> None:
    parser, requests = parser_for()

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 smino vacancies from the complete visible official Personio catalog"
    )
    assert requests == [
        "smino.jobs.personio.com/",
        "smino.jobs.personio.com/job/2691240",
        "smino.jobs.personio.com/job/2756903",
        "smino.jobs.personio.com/job/2608241",
    ]
    assert [job.title for job in result.jobs] == list(TITLES)

    first = result.jobs[0]
    assert first.source == "smino"
    assert first.company == "smino AG"
    assert first.location == "Zürich, Switzerland"
    assert first.url == "https://smino.jobs.personio.com/job/2691240?language=de"
    assert first.apply_url == ("https://smino.jobs.personio.com/job/2691240/apply?language=de")
    assert first.posted_at == "2026-06-30"
    assert first.employment_type == "Festanstellung · Vollzeit · 100%"
    assert first.description and first.description.startswith("Deine Aufgaben\n")
    assert first.raw["detail"]["location_country"] == "CH"

    second = result.jobs[1]
    assert second.employment_type == "Festanstellung · Teilzeit · 80%"
    assert result.jobs[2].location == "Barcelona, Spain (Remote)"
    assert result.jobs[2].raw["detail"]["location_country"] == "ES"


def test_smino_preserves_listing_metadata_when_detail_fails() -> None:
    parser, _ = parser_for(
        page=listing_html([listing_card(2)]),
        details={JOB_IDS[2]: 503},
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == TITLES[2]
    assert job.location == "Barcelona, Spain (Remote)"
    assert job.apply_url == ("https://smino.jobs.personio.com/job/2608241/apply?language=de")
    assert job.posted_at is None
    assert job.employment_type == "Festanstellung · Vollzeit"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_smino_accepts_explicit_empty_catalog() -> None:
    parser, requests = parser_for(page=listing_html([]), details={})

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert requests == ["smino.jobs.personio.com/"]


@pytest.mark.parametrize(
    "page",
    [
        listing_html(title="Unrelated jobs"),
        listing_html(logo_url="https://example.com/logo.png"),
        listing_html().replace("Offene Stellen", "Jobs", 1),
        listing_html().replace("?language=de", "?language=en", 1),
    ],
)
def test_smino_rejects_unexpected_listing_identity(page: str) -> None:
    parser, _ = parser_for(page=page)

    with pytest.raises(DirectCompanyRequestError):
        parser.search(LinkedInSearchRequest())


def test_smino_rejects_malformed_duplicate_and_excess_catalogs() -> None:
    malformed, _ = parser_for(
        page=listing_html([listing_card(0).replace("<span>Vollzeit</span>", "")])
    )
    duplicate, _ = parser_for(
        page=listing_html([listing_card(0), listing_card(1, job_id=JOB_IDS[0])])
    )
    excess, _ = parser_for(page=listing_html([listing_card(0), listing_card(1)]), max_jobs=1)

    for parser in (malformed, duplicate, excess):
        with pytest.raises(DirectCompanyRequestError):
            parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Different vacancy"),
        ("identifier", {"name": "smino AG", "value": "wrong-89984"}),
        (
            "jobLocation",
            {"address": {"addressLocality": "Bern", "addressCountry": "CH"}},
        ),
        ("employmentType", "PART_TIME"),
        ("datePosted", "not-a-date"),
    ],
)
def test_smino_discards_inconsistent_detail(field: str, value: object) -> None:
    posting = job_posting(0)
    posting[field] = value
    parser, _ = parser_for(
        page=listing_html([listing_card(0)]),
        details={JOB_IDS[0]: detail_html(0, posting=posting)},
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert "detail" not in job.raw
    assert "inconsistent vacancy data" in str(job.raw["detail_error"])


def test_smino_wraps_listing_request_failures() -> None:
    parser, _ = parser_for(page_status=503)

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_smino_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["smino"]
    assert isinstance(parser, SminoJobsParser)
    assert parser.base_url == settings.smino_jobs_base_url
    assert parser.max_jobs == settings.smino_jobs_max_jobs
    assert parser.detail_workers == settings.smino_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "smino", "filters": {}},
            "sources": ["smino", "smino"],
        }
    )
    assert request.sources == ["smino"]


def test_smino_jobs_render_as_direct_company_imports() -> None:
    parser, _ = parser_for(page=listing_html([listing_card(0)]))
    job = parser.search(LinkedInSearchRequest()).jobs[0]
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"smino-{JOB_IDS[0]}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "smino AG import"
    assert stored["id"] == f"smino-{JOB_IDS[0]}"
