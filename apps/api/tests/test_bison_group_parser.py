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
from app.services.parsers.companies.bison_group import (
    BISON_GROUP_MEDIUM_ID,
    BISON_GROUP_RESULTS_PER_PAGE,
    BisonGroupJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.bison.test/karriere/offene-stellen/"
API_URL = "https://ohws.test/public/v1/medium/1008012/jobs"


def viewkey(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def listing_record(
    index: int,
    *,
    country: str = "Deutschland",
) -> dict[str, object]:
    key = viewkey(index)
    city = "Sursee" if country == "Schweiz" else "Kaiserslautern"
    return {
        "id": str(10_140_000 + index),
        "hk_id": str(1_018_000 + index),
        "viewkey": key,
        "title": f"Security Analyst {index} (w/m/d)",
        "attributes": {
            "10": ["IT Specialists"],
            "20": ["Mitarbeitende"],
            "30": [city],
        },
        "szas": {
            "sza_title": f"Security Analyst {index} (w/m/d)",
            "sza_apply_link": (
                "https://fenaco-career.talent-soft.com/Pages/Offre/"
                f"detailoffre.aspx?idOffre={9_000 + index}&idOrigine=502&"
                f"offerReference=2026-{9_000 + index}&action=jobapplication"
            ),
            "sza_department": "Bison",
            "sza_location": f"Bison Group, Allee 1A, {city}, {country}",
            "sza_location.city": city,
            "sza_pensum.min": "80",
            "sza_pensum.max": "100",
            "sza_introduction": "Secure business-critical Swiss systems.",
            "sza_tasks": "<ul><li>Analyse incidents</li><li>Improve controls</li></ul>",
            "sza_requirements": "<ul><li>Cybersecurity experience</li></ul>",
            "sza_company_profil": "Bison creates modern software solutions.",
        },
        "links": {"directlink": f"https://ohws.prospective.ch/public/v1/jobs/{key}"},
        "start_date": "2026-08-09T22:00:00Z",
        "end_date": "2027-08-08T21:59:59Z",
        "language": "de",
    }


def listing_payload(
    records: list[dict[str, object]],
    *,
    total: int,
    offset: int,
) -> dict[str, object]:
    return {
        "medium_id": BISON_GROUP_MEDIUM_ID,
        "medium_name": None,
        "total": total,
        "offset": offset,
        "jobs": records,
        "filtercount": None,
    }


def detail_page(
    index: int,
    *,
    country: str = "Schweiz",
    organization: str = "Bison Schweiz AG",
) -> str:
    key = viewkey(index)
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": f"Security Analyst {index} (w/m/d)",
        "description": (
            "<h3>Secure business-critical systems.</h3><br>"
            "<p><div>DAS MACHST DU</div><br>"
            "<ul><li>Analyse incidents</li><li>Improve controls</li></ul></p>"
        ),
        "datePosted": "2026-08-10",
        "validThrough": "2027-08-08",
        "employmentType": "PART_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": organization,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": "Sursee",
                "postalCode": "6210",
            },
        },
    }
    return (
        "<html><body>"
        f'<a href="https://ohws.prospective.ch/public/v1/redirect/{key}/ats/">'
        "Jetzt bewerben</a>"
        f'<script type="application/ld+json">{json.dumps(schema)}</script>'
        "</body></html>"
    )


def test_bison_group_scans_full_catalog_and_enriches_swiss_jobs() -> None:
    records = [listing_record(index) for index in range(98)]
    records[0] = listing_record(0, country="Schweiz")
    records[97] = listing_record(97, country="Schweiz")
    requested_offsets: list[int] = []
    detail_ids: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/medium/1008012/jobs"):
            assert request.method == "GET"
            assert request.url.params["lang"] == "de"
            assert request.url.params["limit"] == str(BISON_GROUP_RESULTS_PER_PAGE)
            offset = int(request.url.params["offset"])
            requested_offsets.append(offset)
            return httpx.Response(
                200,
                json=listing_payload(
                    records[offset : offset + BISON_GROUP_RESULTS_PER_PAGE],
                    total=len(records),
                    offset=offset,
                ),
                request=request,
            )

        assert request.headers["accept"].startswith("text/html")
        key = request.url.path.rsplit("/", maxsplit=1)[-1]
        index = int(key.rsplit("-", maxsplit=1)[-1])
        detail_ids.append(index)
        return httpx.Response(200, text=detail_page(index), request=request)

    result = BisonGroupJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requested_offsets == [0, 96]
    assert detail_ids == [0, 97]
    assert len(result.jobs) == 2
    assert result.message == (
        "Scanned 2 Bison Group Swiss vacancies from 98 global catalog records "
        "across 2 API page requests"
    )
    job = result.jobs[0]
    assert job.source == "bison_group"
    assert job.title == "Security Analyst 0 (w/m/d)"
    assert job.company == "Bison Schweiz AG"
    assert job.location == "Sursee, Schweiz"
    assert job.url == (
        "https://ohws.prospective.ch/public/v1/jobs/00000000-0000-4000-8000-000000000000"
    )
    assert job.apply_url == (
        "https://ohws.prospective.ch/public/v1/redirect/00000000-0000-4000-8000-000000000000/ats/"
    )
    assert job.posted_at == "2026-08-10"
    assert job.employment_type == "Part-time, 80–100%"
    assert job.seniority == "Mitarbeitende"
    assert job.description == (
        "Secure business-critical systems.\n\n"
        "DAS MACHST DU\n\n"
        "- Analyse incidents\n- Improve controls"
    )
    assert job.raw["listing_offset"] == 0
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 98


def test_bison_group_retries_shifted_pages_until_global_ids_are_stable() -> None:
    records = [listing_record(index) for index in range(98)]
    records[0] = listing_record(0, country="Schweiz")
    records[97] = listing_record(97, country="Schweiz")
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/medium/1008012/jobs"):
            return httpx.Response(503, request=request)
        offset = int(request.url.params["offset"])
        requested_offsets.append(offset)
        if offset == 0:
            page = records[:96]
        elif requested_offsets.count(96) == 1:
            page = [records[95], records[97]]
        else:
            page = records[96:]
        return httpx.Response(
            200,
            json=listing_payload(page, total=98, offset=offset),
            request=request,
        )

    result = BisonGroupJobsParser(
        max_catalog_passes=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert requested_offsets == [0, 96, 0, 96]
    assert len(result.jobs) == 2
    assert result.message.endswith("across 4 API page requests")
    assert "503 Service Unavailable" in str(result.jobs[0].raw["detail_error"])


def test_bison_group_preserves_swiss_listing_when_detail_fails() -> None:
    record = listing_record(0, country="Schweiz")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/medium/1008012/jobs"):
            return httpx.Response(
                200,
                json=listing_payload([record], total=1, offset=0),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        BisonGroupJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.location == "Sursee, Schweiz"
    assert job.posted_at == "2026-08-09T22:00:00Z"
    assert job.apply_url and "talent-soft.com" in job.apply_url
    assert job.description and "Secure business-critical" in job.description
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("mutations", "message"),
    [
        ({"medium_id": "another-medium"}, "another medium ID"),
        ({"jobs": {}}, "invalid jobs"),
    ],
)
def test_bison_group_rejects_invalid_catalog_payloads(
    mutations: dict[str, object],
    message: str,
) -> None:
    payload = listing_payload([listing_record(0)], total=1, offset=0)
    payload.update(mutations)
    parser = BisonGroupJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_bison_group_rejects_incomplete_listing_record() -> None:
    record = listing_record(0, country="Schweiz")
    record["links"] = {"directlink": "https://evil.test/job"}
    parser = BisonGroupJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload([record], total=1, offset=0),
                request=request,
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parser.search(LinkedInSearchRequest())


def test_bison_group_enforces_catalog_page_limit() -> None:
    parser = BisonGroupJobsParser(
        max_pages=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=listing_payload(
                    [listing_record(index) for index in range(96)],
                    total=97,
                    offset=0,
                ),
                request=request,
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_bison_group_wraps_listing_request_failures() -> None:
    parser = BisonGroupJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bison_group_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bison_group"]
    assert isinstance(parser, BisonGroupJobsParser)
    assert parser.base_url == settings.bison_group_jobs_base_url
    assert parser.api_url == settings.bison_group_jobs_api_url
    assert parser.max_pages == settings.bison_group_jobs_max_pages
    assert parser.max_catalog_passes == settings.bison_group_jobs_max_catalog_passes
    assert parser.detail_workers == settings.bison_group_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bison Group", "filters": {}},
            "sources": ["bison_group", "bison_group"],
        }
    )
    assert request.sources == ["bison_group"]


def test_bison_group_jobs_render_as_direct_company_imports() -> None:
    parsed = BisonGroupJobsParser().normalize_job(listing_record(0, country="Schweiz"))
    stored = parsed_job_to_stored_job(
        parsed,
        job_id="bison_group-10140000",
        added_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
    )

    assert stored["id"] == "bison_group-10140000"
    assert stored["logo"] == "company"
    assert stored["department"] == "Bison Group import"
    assert stored["company"] == "Bison Schweiz AG"
