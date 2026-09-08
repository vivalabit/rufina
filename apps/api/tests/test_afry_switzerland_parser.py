from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.afry_switzerland import (
    AfrySwitzerlandJobsParser,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://afry.com/de-ch/karriere/verfugbare-stellen"
CATALOG_URL = "https://afry.test/de-ch/api/jobs"
DETAIL_API_URL = "https://api.smart.test/v1/companies/AFRY/postings"
JOB_IDS = ("744000143442729", "744000143292492", "744000143291669")


def listing_record(
    index: int,
    *,
    country: str = "ch",
    job_id: str | None = None,
) -> dict[str, object]:
    resolved_id = job_id or JOB_IDS[index]
    reference = f"REF{13930 + index}H"
    city = "Zürich" if index < 2 else "Ingenbohl"
    return {
        "Id": int(resolved_id),
        "Title": f"Projektleiter:in Infrastruktur {index} 80-100% - {city}",
        "CompetenceAreas": [{"Id": "2755792", "Name": "Project Management"}],
        "Language": "de",
        "Location": [country],
        "Cities": [
            {
                "Id": city,
                "Name": city,
                "RegionId": None,
                "CountryId": country,
            }
        ],
        "Regions": [],
        "Countries": [{"Id": country, "Name": "Schweiz" if country == "ch" else "Deutschland"}],
        "LastApplyDate": f"2026-08-{14 - index:02d}",
        "DetailUrl": (
            f"/en/career/available-jobs/{reference}-projektleiterin-infrastruktur-{index}"
        ),
    }


def global_record() -> dict[str, object]:
    return {
        "Id": 744000140000001,
        "Countries": [{"Id": "de", "Name": "Deutschland"}],
    }


def catalog_payload(indexes: list[int]) -> dict[str, object]:
    return {
        "Adverts": [*(listing_record(index) for index in indexes), global_record()],
        "CompetenceAreas": [],
        "Countries": [
            {"Id": "de", "Name": "Deutschland"},
            {"Id": "ch", "Name": "Schweiz"},
        ],
        "Regions": [],
        "Cities": [],
        "DefaultCountry": "ch",
        "CacheCold": False,
    }


def detail_record(index: int) -> dict[str, object]:
    job_id = JOB_IDS[index]
    city = "Zürich" if index < 2 else "Ingenbohl"
    title = f"Projektleiter:in Infrastruktur {index} 80-100% - {city}"
    slug = f"projektleiter-in-infrastruktur-{index}"
    return {
        "id": job_id,
        "name": title,
        "refNumber": f"REF{13930 + index}H",
        "company": {"name": "AFRY", "identifier": "AFRY"},
        "location": {
            "city": city,
            "region": "ZH" if city == "Zürich" else "SZ",
            "country": "ch",
            "remote": False,
            "hybrid": index == 0,
            "fullLocation": f"{city}, {'ZH' if city == 'Zürich' else 'SZ'}, Switzerland",
        },
        "releasedDate": f"2026-08-{14 - index:02d}T06:09:51.859Z",
        "postingUrl": f"https://jobs.smartrecruiters.com/AFRY/{job_id}-{slug}",
        "applyUrl": f"https://jobs.smartrecruiters.com/AFRY/{job_id}-{slug}?oga=true",
        "active": True,
        "visibility": "PUBLIC",
        "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        "experienceLevel": {"id": "associate", "label": "Associate"},
        "customField": [
            {"fieldLabel": "Country/Region", "valueLabel": "Switzerland"},
            {"fieldLabel": "Legal entity", "valueLabel": "410-AFRY Schweiz AG"},
        ],
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "title": "Unternehmensbeschreibung",
                    "text": "<p>AFRY gestaltet die Zukunft.</p>",
                },
                "jobDescription": {
                    "title": "Stellenbeschreibung",
                    "text": "<ul><li>Infrastrukturprojekte leiten</li></ul>",
                },
                "qualifications": {"title": "Qualifikationen", "text": ""},
            }
        },
    }


def test_afry_scans_full_swiss_snapshot_and_enriches_details() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url == httpx.URL(CATALOG_URL):
            return httpx.Response(200, json=catalog_payload([0, 1, 2]), request=request)
        job_id = request.url.path.rsplit("/", maxsplit=1)[-1]
        return httpx.Response(
            200,
            json=detail_record(JOB_IDS.index(job_id)),
            request=request,
        )

    result = AfrySwitzerlandJobsParser(
        base_url=BASE_URL,
        catalog_url=CATALOG_URL,
        detail_api_url=DETAIL_API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(result.jobs) == 3
    assert result.message == ("Scanned 3 AFRY Switzerland vacancies from 4 global catalog records")
    assert requests == [
        "/de-ch/api/jobs",
        "/v1/companies/AFRY/postings/744000143442729",
        "/v1/companies/AFRY/postings/744000143292492",
        "/v1/companies/AFRY/postings/744000143291669",
    ]

    job = result.jobs[0]
    assert job.source == "afry_switzerland"
    assert job.title == "Projektleiter:in Infrastruktur 0 80-100% - Zürich"
    assert job.company == "AFRY"
    assert job.location == "Zürich, ZH, Switzerland (Hybrid)"
    assert job.url == (
        "https://afry.com/en/career/available-jobs/REF13930H-projektleiterin-infrastruktur-0"
    )
    assert job.apply_url == (
        "https://jobs.smartrecruiters.com/AFRY/744000143442729-"
        "projektleiter-in-infrastruktur-0?oga=true"
    )
    assert job.posted_at == "2026-08-14T06:09:51.859Z"
    assert job.employment_type == "Full-time (80–100%)"
    assert job.seniority == "Associate"
    assert job.description == (
        "Unternehmensbeschreibung\nAFRY gestaltet die Zukunft.\n\n"
        "Stellenbeschreibung\n- Infrastrukturprojekte leiten"
    )
    assert job.raw["reference"] == "REF13930H"
    assert job.raw["total_available"] == 3
    assert job.raw["global_total_available"] == 4


def test_afry_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CATALOG_URL):
            return httpx.Response(200, json=catalog_payload([0]), request=request)
        return httpx.Response(503, request=request)

    job = (
        AfrySwitzerlandJobsParser(
            catalog_url=CATALOG_URL,
            detail_api_url=DETAIL_API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Projektleiter:in Infrastruktur 0 80-100% - Zürich"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.posted_at == "2026-08-14"
    assert job.employment_type == "80–100%"
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**catalog_payload([0]), "CacheCold": True}, "cache is not ready"),
        ({**catalog_payload([0]), "DefaultCountry": "de"}, "Swiss default filter"),
        (
            {
                **catalog_payload([0]),
                "Adverts": [
                    listing_record(0),
                    listing_record(1, job_id=JOB_IDS[0]),
                ],
            },
            "duplicate vacancy IDs",
        ),
        (
            {
                **catalog_payload([0]),
                "Adverts": [
                    {
                        **listing_record(0),
                        "Cities": [
                            {
                                "Id": "Zürich",
                                "Name": "Zürich",
                                "RegionId": None,
                                "CountryId": "de",
                            }
                        ],
                    }
                ],
            },
            "incomplete or non-Swiss vacancy",
        ),
    ],
)
def test_afry_rejects_invalid_catalogs(payload: object, message: str) -> None:
    parser = AfrySwitzerlandJobsParser(
        catalog_url=CATALOG_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_afry_enforces_catalog_limit_and_wraps_http_errors() -> None:
    limited = AfrySwitzerlandJobsParser(
        catalog_url=CATALOG_URL,
        max_catalog_records=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=catalog_payload([0]),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        limited.search(LinkedInSearchRequest())

    unavailable = AfrySwitzerlandJobsParser(
        catalog_url=CATALOG_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_afry_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["afry_switzerland"]
    assert isinstance(parser, AfrySwitzerlandJobsParser)
    assert parser.base_url == settings.afry_switzerland_jobs_base_url
    assert parser.catalog_url == settings.afry_switzerland_jobs_catalog_url
    assert parser.detail_api_url == settings.afry_switzerland_jobs_detail_api_url
    assert parser.max_catalog_records == settings.afry_switzerland_jobs_max_catalog_records
    assert parser.detail_workers == settings.afry_switzerland_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AFRY", "filters": {}},
            "sources": ["afry_switzerland", "afry_switzerland"],
        }
    )
    assert request.sources == ["afry_switzerland"]


def test_afry_jobs_render_as_direct_company_imports() -> None:
    listing = listing_record(0)
    record = {
        **listing,
        "id": JOB_IDS[0],
        "name": listing["Title"],
        "public_url": (
            "https://afry.com/en/career/available-jobs/REF13930H-projektleiterin-infrastruktur-0"
        ),
        "detail": detail_record(0),
    }
    parsed = AfrySwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        parsed,
        job_id="afry_switzerland-744000143442729",
        added_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == "afry_switzerland-744000143442729"
    assert stored["logo"] == "company"
    assert stored["department"] == "AFRY Switzerland import"
    assert stored["company"] == "AFRY"


def test_afry_keeps_only_verified_swiss_cities_for_multicountry_role() -> None:
    from app.services.parsers.companies.afry_switzerland import validate_listing_record

    record = listing_record(0)
    record["Countries"].append({"Id": "de", "Name": "Deutschland"})
    record["Cities"].append({"Id": "Munich", "Name": "Munich", "CountryId": "de"})
    parsed = validate_listing_record(record, page_url=BASE_URL, detail_api_url=DETAIL_API_URL)
    assert parsed["city_names"] == ["Zürich"]
    record["Cities"] = record["Cities"][1:]
    with pytest.raises(DirectCompanyRequestError):
        validate_listing_record(record, page_url=BASE_URL, detail_api_url=DETAIL_API_URL)


def test_afry_enriches_multicountry_role_without_relabeling_foreign_detail_city() -> None:
    from app.services.parsers.companies.afry_switzerland import (
        parse_detail_payload,
        validate_listing_record,
    )

    record = listing_record(0)
    record["Countries"].append({"Id": "de", "Name": "Deutschland"})
    record["Cities"].append({"Id": "Hamburg", "Name": "Hamburg", "CountryId": "de"})
    listing = validate_listing_record(record, page_url=BASE_URL, detail_api_url=DETAIL_API_URL)
    detail = detail_record(0)
    detail["location"].update(country="de", city="Hamburg", fullLocation="Hamburg, Germany")
    listing["detail"] = parse_detail_payload(
        detail,
        expected_job_id=listing["id"],
        expected_title=listing["name"],
        expected_reference=listing["reference"],
        expected_cities=listing["city_names"],
        listed_locations=listing["Cities"],
    )
    job = AfrySwitzerlandJobsParser().normalize_job(listing)
    assert job.location == "Zürich, Switzerland"
    assert job.description
    detail["location"]["city"] = "London"
    with pytest.raises(DirectCompanyRequestError):
        parse_detail_payload(
            detail,
            expected_job_id=listing["id"],
            expected_title=listing["name"],
            expected_reference=listing["reference"],
            expected_cities=listing["city_names"],
            listed_locations=listing["Cities"],
        )
