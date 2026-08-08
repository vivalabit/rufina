from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bdo_switzerland import (
    BdoSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def publication(
    *,
    publication_id: str,
    title: str,
    city: str,
    custom_location: str = "",
    language: str = "de",
) -> dict[str, str]:
    portal_id = "3505fa5b-0c08-49ef-852b-1a20eab2630e"
    return {
        "JobId": f"job-{publication_id}",
        "PublicationId": publication_id,
        "JobTitle": title,
        "CompanyName": "",
        "PlaceOfWorkCity": city,
        "PlaceOfWorkState": "ZH",
        "PlaceOfWorkCountry": "CH",
        "PositionDepartmentName": "Digital",
        "PositionLevelOfEmployment": "100",
        "PublicationLanguage": language,
        "PublicationStartDate": "2026-08-06",
        "PositionValidFrom": "2026-08-01",
        "PublicationUrlAbacusJobPortal": (
            f"https://app.jobportal.abaservices.ch/job-advertisement/"
            f"{portal_id}/{publication_id}?jp=ABACUS"
        ),
        "ApplicationUrl": (
            f"https://app.jobportal.abaservices.ch/application-process/"
            f"{portal_id}/{publication_id}?jp=ABACUS"
        ),
        "Organization": (
            "&lt;p&gt;&lt;strong&gt;Arbeiten bei BDO&lt;/strong&gt;&lt;/p&gt;"
            "&lt;p&gt;Einzigartig. Vielseitig. Ambitioniert.&lt;/p&gt;"
        ),
        "Introduction": (
            "&lt;p&gt;&lt;strong&gt;Dein nächster Karriereschritt&lt;/strong&gt;&lt;/p&gt;"
        ),
        "Tasks": (
            "&lt;p&gt;&lt;strong&gt;Das bewegst du&lt;/strong&gt;&lt;/p&gt;"
            "&lt;ul&gt;&lt;li&gt;Du entwickelst digitale Lösungen.&lt;/li&gt;&lt;/ul&gt;"
        ),
        "Requirements": (
            "&lt;p&gt;&lt;strong&gt;Damit gelingt es dir&lt;/strong&gt;&lt;/p&gt;"
            "&lt;ul&gt;&lt;li&gt;Du arbeitest gerne im Team.&lt;/li&gt;&lt;/ul&gt;"
        ),
        "Benefits": "",
        "Closure": "",
        "PositionAdditionalFieldLocation": "",
        "u_b_jobs_freiefelder_xxx__userfield1": custom_location,
    }


def test_bdo_switzerland_scans_and_normalizes_full_catalog() -> None:
    records = [
        publication(
            publication_id="pub-1001",
            title="Abacus Consultant Finanzen (w/m/d) 80-100%",
            city="Zürich",
            custom_location="Deutschschweiz",
        ),
        publication(
            publication_id="pub-1002",
            title="Responsable Audit (h/f/d) 80 % à 100 %",
            city="Lausanne",
            language="fr",
        ),
    ]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=records)

    parser = BdoSwitzerlandJobsParser(
        base_url="https://www.bdo.test/en-gb/careers/open-jobs",
        api_url="https://api.bdo.test/publications",
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 BDO Switzerland vacancies from the full catalog endpoint"
    )
    assert len(requests) == 1
    assert requests[0].url == "https://api.bdo.test/publications"
    assert requests[0].headers["referer"] == parser.base_url
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "bdo_switzerland"
    assert first.title == "Abacus Consultant Finanzen (w/m/d) 80-100%"
    assert first.company == "BDO AG"
    assert first.location == "Deutschschweiz"
    assert first.url == records[0]["PublicationUrlAbacusJobPortal"]
    assert first.apply_url == records[0]["ApplicationUrl"]
    assert first.posted_at == "2026-08-06"
    assert first.employment_type == "80-100%"
    assert first.description == (
        "Arbeiten bei BDO\nEinzigartig. Vielseitig. Ambitioniert.\n\n"
        "Dein nächster Karriereschritt\n\n"
        "Das bewegst du\nDu entwickelst digitale Lösungen.\n\n"
        "Damit gelingt es dir\nDu arbeitest gerne im Team."
    )
    assert first.raw["PublicationId"] == "pub-1001"
    assert result.jobs[1].employment_type == "80-100%"
    assert result.jobs[1].location == "Lausanne"


def test_bdo_switzerland_deduplicates_publications_when_requested() -> None:
    record = publication(
        publication_id="pub-1001",
        title="Senior Consultant (w/m/d) 100%",
        city="Zürich",
    )
    parser = BdoSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[record, record])
        )
    )

    deduplicated = parser.search(LinkedInSearchRequest(deduplicate=True))
    complete = parser.search(LinkedInSearchRequest(deduplicate=False))

    assert len(deduplicated.jobs) == 1
    assert len(complete.jobs) == 2


@pytest.mark.parametrize("payload", [{"jobs": []}, [{}]])
def test_bdo_switzerland_rejects_invalid_catalog(payload: object) -> None:
    parser = BdoSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="jobs response"):
        parser.search(LinkedInSearchRequest())


def test_bdo_switzerland_wraps_api_failures() -> None:
    parser = BdoSwitzerlandJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(503, text="temporarily unavailable")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bdo_switzerland_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bdo_switzerland"]
    assert isinstance(parser, BdoSwitzerlandJobsParser)
    assert parser.base_url == settings.bdo_switzerland_jobs_base_url
    assert parser.api_url == settings.bdo_switzerland_jobs_api_url
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "BDO Switzerland", "filters": {}},
            "sources": ["bdo_switzerland", "bdo_switzerland"],
        }
    )
    assert request.sources == ["bdo_switzerland"]


def test_bdo_switzerland_jobs_render_as_direct_company_imports() -> None:
    parser = BdoSwitzerlandJobsParser()
    job = parser.normalize_job(
        publication(
            publication_id="pub-1001",
            title="Abacus Consultant Finanzen (w/m/d) 80-100%",
            city="Zürich",
        )
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="bdo_switzerland-pub-1001",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "BDO Switzerland import"
    assert stored["id"] == "bdo_switzerland-pub-1001"
