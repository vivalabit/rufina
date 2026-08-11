from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.lufthansa_group_switzerland import (
    DIVISION_IDS,
    LufthansaGroupSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = (
    "https://apply.lufthansagroup.careers/index.php?ac=search_result"
    "&search_criterion_division%5B%5D=5926"
    "&search_criterion_division%5B%5D=9114"
    "&search_criterion_division%5B%5D=5988"
    "&search_criterion_division%5B%5D=6006"
    "&search_criterion_channel%5B%5D=12"
)
API_URL = "https://api-apply.lufthansagroup.careers/search/"
SWISS_AS_APPLY_URL = "https://swissas.teamtailor.com/jobs/7916983-release-manager"


def job_url(job_id: str) -> str:
    return f"https://apply.lufthansagroup.careers/index.php?ac=jobad&id={job_id}"


def apply_url(job_id: str) -> str:
    return f"https://apply.lufthansagroup.careers/index.php?ac=application&jobad_id={job_id}"


def api_record(
    job_id: str,
    *,
    title: str,
    company: str = "Swiss International Air Lines AG",
    country_name: str = "Switzerland",
    country_code: str = "CH",
    city: str = "Zürich/Kloten",
    postal_code: str = "8302",
    position_id: str | None = None,
    offering_type: str = "Temporary",
    schedule: str = "Full-time or part-time",
    career_level: str = "University internship",
) -> dict[str, object]:
    return {
        "MatchedObjectId": job_id,
        "MatchedObjectDescriptor": {
            "ID": job_id,
            "PositionID": position_id or f"J000{job_id}",
            "PositionTitle": title,
            "PublicationCode": f"publication-{job_id}",
            "PositionURI": job_url(job_id),
            "PublicationEndDate": "2026-08-31",
            "JobCategory": [{"Name": "Other"}],
            "CareerLevel": [{"Name": career_level}, {"Name": career_level}],
            "PositionOfferingType": [{"Name": offering_type}],
            "ParentOrganizationName": company,
            "PositionLocation": [
                {
                    "CountryName": country_name,
                    "CountryCode": country_code,
                    "CityName": city,
                    "PostalCode": postal_code,
                }
            ],
            "PositionSchedule": [{"Name": schedule}],
            "PublicationStartDate": "2026-08-11",
        },
    }


def api_payload(records: list[dict[str, object]], *, total: int) -> dict[str, object]:
    return {
        "LanguageCode": "EN",
        "SearchParameters": {"Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}]},
        "SearchResult": {
            "SearchResultCount": len(records),
            "SearchResultCountAll": total,
            "SearchResultItems": records,
            "UserArea": {},
        },
    }


def detail_html(
    job_id: str,
    *,
    title: str,
    company: str = "Swiss International Air Lines AG",
    city: str = "Zürich/Kloten",
    postal_code: str = "8302",
    country: str = "CH",
    position_id: str | None = None,
    application_url: str | None = None,
) -> str:
    schema = {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "directApply": "true",
        "datePosted": "2026-08-11",
        "validThrough": "2026-08-31",
        "title": title,
        "description": (
            "<p>Support Data &amp; AI projects across the Lufthansa Group.</p>"
            "<h2>Tasks</h2><ul><li>Build analytical solutions</li></ul>"
        ),
        "hiringOrganization": {
            "@type": "Organization",
            "name": company,
        },
        "jobLocation": [
            {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": city,
                    "postalCode": postal_code,
                    "addressCountry": country,
                },
            }
        ],
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": position_id or f"J000{job_id}",
        },
    }
    return f"""
    <html><head>
      <link rel="canonical"
        href="https://apply.lufthansagroup.careers//index.php?ac=jobad&amp;id={job_id}">
    </head><body>
      <div id="jobad-container">
        <a class="lh-jobad-btn-submit js-button-apply-redirect"
          href="{application_url or apply_url(job_id)}">
          apply
        </a>
      </div>
      <script type="application/ld+json">{json.dumps([schema])}</script>
    </body></html>
    """


def official_records() -> list[dict[str, object]]:
    return [
        api_record(
            "134020",
            title=(
                "Internship in Data & AI Innovation & Portfolio "
                "(limited 6-8 months, 80-100%, all genders)"
            ),
        ),
        api_record(
            "132774",
            title="Release Manager (100%, all genders) at SWISS Aviation Software",
            company="Swiss AviationSoftware Ltd.",
            city="Allschwil",
            postal_code="4123",
            offering_type="Permanent",
            schedule="Full time",
            career_level="Direct entry",
        ),
        api_record(
            "133920",
            title="Cargo Sales Executive",
            country_name="India",
            country_code="IN",
            city="Bengaluru",
            postal_code="560300",
            offering_type="Permanent",
            schedule="Full time",
            career_level="Direct entry",
        ),
    ]


def request_payload(request: httpx.Request) -> dict[str, object]:
    return json.loads(request.url.params["data"])


def test_lufthansa_group_scans_complete_catalog_and_keeps_only_swiss_jobs() -> None:
    requests: list[httpx.Request] = []
    records = official_records()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api-apply.lufthansagroup.careers":
            payload = request_payload(request)
            search_parameters = payload["SearchParameters"]
            assert isinstance(search_parameters, dict)
            first_item = search_parameters["FirstItem"]
            assert isinstance(first_item, int)
            offset = first_item - 1
            return httpx.Response(
                200,
                json=api_payload(records[offset : offset + 2], total=3),
            )
        query = parse_qs(request.url.query.decode())
        job_id = query["id"][0]
        record = next(
            item["MatchedObjectDescriptor"] for item in records if item["MatchedObjectId"] == job_id
        )
        assert isinstance(record, dict)
        return httpx.Response(
            200,
            text=detail_html(
                job_id,
                title=str(record["PositionTitle"]),
                company=str(record["ParentOrganizationName"]),
                city=str(record["PositionLocation"][0]["CityName"]),
                postal_code=str(record["PositionLocation"][0]["PostalCode"]),
                application_url=(
                    SWISS_AS_APPLY_URL
                    if record["ParentOrganizationName"] == "Swiss AviationSoftware Ltd."
                    else None
                ),
            ),
        )

    result = LufthansaGroupSwitzerlandJobsParser(
        page_size=2,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    api_requests = [request for request in requests if request.url.host.startswith("api-")]
    assert len(api_requests) == 2
    first_payload = request_payload(api_requests[0])
    assert first_payload["LanguageCode"] == "EN"
    assert first_payload["SearchCriteria"] == [
        {
            "CriterionName": "ParentOrganization",
            "CriterionValue": list(DIVISION_IDS),
        },
        {
            "CriterionName": "PublicationChannel.Code",
            "CriterionValue": ["12"],
        },
    ]
    assert result.message == (
        "Scanned 2 Lufthansa Group Switzerland vacancies from 3 catalog records "
        "across 2 API requests"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "lufthansa_group_switzerland"
    assert first.company == "Swiss International Air Lines AG"
    assert first.location == "8302 Zürich/Kloten, Switzerland"
    assert first.url == job_url("134020")
    assert first.apply_url == apply_url("134020")
    assert first.posted_at == "2026-08-11"
    assert first.employment_type == "Temporary · Full-time or part-time · 80-100%"
    assert first.seniority == "University internship"
    assert first.description and "Support Data & AI projects" in first.description
    assert first.description and "- Build analytical solutions" in first.description
    assert first.raw["total_available"] == 3
    assert first.raw["detail"]["schema"]["@type"] == "JobPosting"
    assert result.jobs[1].company == "Swiss AviationSoftware Ltd."
    assert result.jobs[1].location == "4123 Allschwil, Switzerland"
    assert result.jobs[1].apply_url == SWISS_AS_APPLY_URL


def test_lufthansa_group_rejects_untrusted_external_apply_url() -> None:
    record = official_records()[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api-apply.lufthansagroup.careers":
            return httpx.Response(200, json=api_payload([record], total=1))
        return httpx.Response(
            200,
            text=detail_html(
                "132774",
                title="Release Manager (100%, all genders) at SWISS Aviation Software",
                company="Swiss AviationSoftware Ltd.",
                city="Allschwil",
                postal_code="4123",
                application_url="https://example.com/jobs/7916983-release-manager",
            ),
        )

    job = (
        LufthansaGroupSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == job_url("132774")
    assert job.description is None
    assert "incomplete or mismatched" in str(job.raw["detail_error"])


def test_lufthansa_group_repeats_shifted_pages_until_every_id_is_seen() -> None:
    records = official_records()
    first_page_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal first_page_calls
        if request.url.host != "api-apply.lufthansagroup.careers":
            job_id = parse_qs(request.url.query.decode())["id"][0]
            record = next(
                item["MatchedObjectDescriptor"]
                for item in records
                if item["MatchedObjectId"] == job_id
            )
            assert isinstance(record, dict)
            return httpx.Response(
                200,
                text=detail_html(job_id, title=str(record["PositionTitle"])),
            )
        payload = request_payload(request)
        search_parameters = payload["SearchParameters"]
        assert isinstance(search_parameters, dict)
        first_item = search_parameters["FirstItem"]
        if first_item == 1:
            first_page_calls += 1
            return httpx.Response(200, json=api_payload(records[:2], total=3))
        last_record = records[1] if first_page_calls == 1 else records[2]
        return httpx.Response(200, json=api_payload([last_record], total=3))

    result = LufthansaGroupSwitzerlandJobsParser(
        page_size=2,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest())

    assert first_page_calls == 2
    assert len(result.jobs) == 2
    assert result.message.endswith("across 4 API requests")


def test_lufthansa_group_preserves_listing_when_detail_fails() -> None:
    record = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api-apply.lufthansagroup.careers":
            return httpx.Response(200, json=api_payload([record], total=1))
        return httpx.Response(503, text="temporarily unavailable")

    job = (
        LufthansaGroupSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title and job.title.startswith("Internship in Data & AI")
    assert job.company == "Swiss International Air Lines AG"
    assert job.location == "8302 Zürich/Kloten, Switzerland"
    assert job.apply_url == apply_url("134020")
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


def test_lufthansa_group_rejects_mismatched_detail_but_keeps_listing() -> None:
    record = official_records()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api-apply.lufthansagroup.careers":
            return httpx.Response(200, json=api_payload([record], total=1))
        return httpx.Response(
            200,
            text=detail_html("134020", title="Different vacancy"),
        )

    job = (
        LufthansaGroupSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_lufthansa_group_accepts_official_detail_title_suffix() -> None:
    record = api_record(
        "133935",
        title="Simulator Maintenance Engineer, 80-100% (m/f/d)",
        company="Lufthansa Aviation Training Switzerland AG",
        city="Zurich",
        postal_code="8152",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api-apply.lufthansagroup.careers":
            return httpx.Response(200, json=api_payload([record], total=1))
        return httpx.Response(
            200,
            text=detail_html(
                "133935",
                title=(
                    "Simulator Maintenance Engineer, 80-100% (m/f/d) - "
                    "immediately or upon agreement"
                ),
                company="Lufthansa Aviation Training Switzerland AG",
                city="Zurich",
                postal_code="8152",
            ),
        )

    job = (
        LufthansaGroupSwitzerlandJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.description and "Support Data & AI projects" in job.description
    assert job.title and job.title.endswith("immediately or upon agreement")


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"LanguageCode": "EN"}, "missing its search result"),
        (
            api_payload(
                [
                    api_record(
                        "134020",
                        title="Internship",
                        company="Unexpected Lufthansa Company",
                    )
                ],
                total=1,
            ),
            "unexpected vacancy",
        ),
    ],
)
def test_lufthansa_group_rejects_malformed_or_unexpected_api_records(
    payload: dict[str, object],
    error: str,
) -> None:
    parser = LufthansaGroupSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )

    with pytest.raises(DirectCompanyRequestError, match=error):
        parser.search(LinkedInSearchRequest())


def test_lufthansa_group_enforces_catalog_page_limit() -> None:
    parser = LufthansaGroupSwitzerlandJobsParser(
        page_size=1,
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=api_payload([official_records()[0]], total=2),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        parser.search(LinkedInSearchRequest())


def test_lufthansa_group_accepts_an_empty_official_catalog() -> None:
    parser = LufthansaGroupSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=api_payload([], total=0)))
    )

    result = parser.search(LinkedInSearchRequest())

    assert result.jobs == []
    assert result.message == (
        "Scanned 0 Lufthansa Group Switzerland vacancies from 0 catalog records "
        "across 1 API request"
    )


def test_lufthansa_group_wraps_listing_request_failures() -> None:
    parser = LufthansaGroupSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_lufthansa_group_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["lufthansa_group_switzerland"]
    assert isinstance(parser, LufthansaGroupSwitzerlandJobsParser)
    assert parser.base_url == settings.lufthansa_group_switzerland_jobs_base_url
    assert parser.api_url == settings.lufthansa_group_switzerland_jobs_api_url
    assert parser.max_pages == settings.lufthansa_group_switzerland_jobs_max_pages
    assert parser.max_catalog_passes == (
        settings.lufthansa_group_switzerland_jobs_max_catalog_passes
    )
    assert parser.detail_workers == (settings.lufthansa_group_switzerland_jobs_detail_workers)
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Lufthansa Group Switzerland", "filters": {}},
            "sources": [
                "lufthansa_group_switzerland",
                "lufthansa_group_switzerland",
            ],
        }
    )
    assert request.sources == ["lufthansa_group_switzerland"]


def test_lufthansa_group_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": "134020",
        "title": "Internship in Data & AI Innovation & Portfolio",
        "company": "Swiss International Air Lines AG",
        "location": "8302 Zürich/Kloten, Switzerland",
        "url": job_url("134020"),
        "is_swiss": True,
    }
    job = LufthansaGroupSwitzerlandJobsParser().normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id="lufthansa_group_switzerland-134020",
        added_at=datetime.now(UTC),
    )

    assert urlsplit(job.url or "").netloc == "apply.lufthansagroup.careers"
    assert stored["logo"] == "company"
    assert stored["department"] == "Lufthansa Group Switzerland import"
    assert stored["id"] == "lufthansa_group_switzerland-134020"
