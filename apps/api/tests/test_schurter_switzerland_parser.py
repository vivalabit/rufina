from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.schurter_switzerland import (
    SCHURTER_APPLY_EMAIL,
    SchurterSwitzerlandJobsParser,
    application_email_url,
    normalize_job,
    parse_catalog_record,
    parse_country_filters,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.schurter.com/de/karriere/offene-stellen?country=CH"
API_URL = "https://www.schurter.com/api/website/v1/jobs"


def contentful_system(
    *,
    entry_id: str,
    content_type: str,
    created_at: str = "2026-08-12T15:41:59.631Z",
    updated_at: str = "2026-08-20T06:32:37.502Z",
) -> dict[str, object]:
    return {
        "space": {"sys": {"type": "Link", "linkType": "Space", "id": "k3bfto4ed09w"}},
        "id": entry_id,
        "type": "Entry",
        "createdAt": created_at,
        "updatedAt": updated_at,
        "environment": {"sys": {"id": "master", "type": "Link", "linkType": "Environment"}},
        "publishedVersion": 12,
        "revision": 2,
        "contentType": {"sys": {"type": "Link", "linkType": "ContentType", "id": content_type}},
        "locale": "de",
    }


def rich_text(*paragraphs: str, bullets: list[str] | None = None) -> dict[str, object]:
    content: list[dict[str, object]] = [
        {
            "nodeType": "paragraph",
            "data": {},
            "content": [{"nodeType": "text", "value": paragraph, "marks": [], "data": {}}],
        }
        for paragraph in paragraphs
    ]
    if bullets:
        content.append(
            {
                "nodeType": "unordered-list",
                "data": {},
                "content": [
                    {
                        "nodeType": "list-item",
                        "data": {},
                        "content": [
                            {
                                "nodeType": "paragraph",
                                "data": {},
                                "content": [
                                    {
                                        "nodeType": "text",
                                        "value": bullet,
                                        "marks": [],
                                        "data": {},
                                    }
                                ],
                            }
                        ],
                    }
                    for bullet in bullets
                ],
            }
        )
    return {"nodeType": "document", "data": {}, "content": content}


def parent_page() -> dict[str, object]:
    return {
        "metadata": {"tags": [], "concepts": []},
        "sys": contentful_system(
            entry_id="ParentPage123456789012",
            content_type="bh-page",
        ),
        "fields": {
            "title": "Offene Stellen bei SCHURTER",
            "slug": "karriere/offene-stellen",
            "modules": [],
            "selectFab": "share",
        },
    }


def job_record(
    index: int,
    *,
    title: str | None = None,
    country: str = "CH",
    contact_email: str = SCHURTER_APPLY_EMAIL,
    with_swiss_metadata: bool = True,
) -> dict[str, object]:
    job_title = title or f"Senior Systems Engineer {index} (80-100%)"
    slug = f"senior-systems-engineer-{index}-80-100"
    fields: dict[str, object] = {
        "title": job_title,
        "slug": slug,
        "parentPage": parent_page(),
        "pageMetadata": {
            "fields": {
                "title": job_title,
                "description": "Arbeiten Sie an sicheren elektronischen Lösungen.",
                "noIndex": False,
                "noFollow": False,
            }
        },
        "selectCountryISO": country,
        "subtitle": "Global IT Organization",
        "positionInformation": rich_text(
            "Sie gestalten moderne IT-Arbeitsplätze und entwickeln zuverlässige "
            "Services für unsere Mitarbeitenden weltweit weiter."
        ),
        "challengesTitle": "Ihre Aufgaben",
        "challenges": rich_text(
            bullets=[
                "Sie verantworten technische Lösungen von der Konzeption bis zum Betrieb.",
                "Sie koordinieren interne Teams, Partner und internationale Standorte.",
            ]
        ),
        "qualificationTitle": "Ihr Profil",
        "qualification": rich_text(
            "Sie verfügen über fundierte technische Erfahrung, kommunizieren sicher "
            "auf Deutsch und Englisch und arbeiten strukturiert."
        ),
        "offerTitle": "Unser Angebot",
        "offer": rich_text(
            "Flexible Arbeitsmodelle, moderne Infrastruktur, Weiterbildung und ein "
            "kollegiales internationales Umfeld erwarten Sie."
        ),
        "companyProfile": rich_text(
            "SCHURTER ist ein weltweit tätiges Schweizer Technologieunternehmen."
        ),
        "contactTitle": "Kontakt",
        "motivationAndContact": rich_text(f"Wir freuen uns auf Ihre Bewerbung an {contact_email}."),
        "addressTitle": "Adresse",
        "address": rich_text(
            "SCHURTER AG\nElectronic Components\nWerkhofstrasse 8 - 12\n6002 Luzern"
        ),
        "contactMail": contact_email,
    }
    if with_swiss_metadata:
        fields["jobsCHMetadata"] = {
            "metadata": {"tags": [], "concepts": []},
            "sys": contentful_system(
                entry_id=f"Metadata{index:013d}",
                content_type="pageJobsCHMetadata",
            ),
            "fields": {
                "title": job_title,
                "place_of_work": "Luzern",
                "job_percentage_from": 80,
                "job_percentage_to": 100,
                "type_of_position": "5 Unlimited employment",
            },
        }
    return {
        "metadata": {
            "tags": [
                {
                    "sys": {
                        "type": "Link",
                        "linkType": "Tag",
                        "id": "website_GLOBAL",
                    }
                }
            ],
            "concepts": [],
        },
        "sys": contentful_system(
            entry_id=f"A{index:021d}",
            content_type="pageJob",
        ),
        "fields": fields,
    }


def test_schurter_scans_complete_swiss_catalog() -> None:
    records = [
        job_record(
            1,
            title="Lead Global Workplace & Service Experience (100%)",
        ),
        job_record(
            2,
            title="Operator Produktion (m/w/d)",
            with_swiss_metadata=False,
        ),
    ]
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/filters"):
            payload = {"values": ["All", "CH", "DE"]}
        else:
            payload = {"total": 2, "data": records}
        return httpx.Response(200, json=payload, request=request)

    result = SchurterSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert calls == [
        (
            "/api/website/v1/jobs/filters",
            {"locale": "de", "isPreview": "false"},
        ),
        (
            "/api/website/v1/jobs/all",
            {
                "locale": "de",
                "filters": "country=CH;page=1",
                "isPreview": "false",
            },
        ),
    ]
    assert result.message == (
        "Scanned 2 SCHURTER Switzerland vacancies across 1 API page from a "
        "verified 2-country catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "schurter_switzerland"
    assert first.title == "Lead Global Workplace & Service Experience (100%)"
    assert first.company == "SCHURTER AG"
    assert first.location == "Switzerland"
    assert first.url == ("https://www.schurter.com/de/jobs/senior-systems-engineer-1-80-100")
    assert first.apply_url == application_email_url(
        first.title,
        public_url=first.url,
    )
    assert first.posted_at == "2026-08-12T15:41:59.631Z"
    assert first.employment_type == "80–100%"
    assert first.description and "Ihre Aufgaben" in first.description
    assert "- Sie verantworten technische Lösungen" in first.description
    assert first.raw["id"] == "A000000000000000000001"
    assert first.raw["catalog_index"] == 0
    assert result.jobs[1].employment_type is None


def test_schurter_paginates_until_the_declared_total() -> None:
    records = [job_record(index) for index in range(1, 11)]
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/filters"):
            return httpx.Response(
                200,
                json={"values": ["All", "CH"]},
                request=request,
            )
        page = int(request.url.params["filters"].rsplit("=", 1)[-1])
        pages.append(page)
        start = (page - 1) * 9
        return httpx.Response(
            200,
            json={"total": 10, "data": records[start : start + 9]},
            request=request,
        )

    result = SchurterSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )

    assert pages == [1, 2]
    assert len(result.jobs) == 10
    assert result.jobs[-1].raw["catalog_index"] == 9


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"values": ["All", "DE"]},
        {"values": ["All", "CH", "CH"]},
        {"values": ["All", "Switzerland", "CH"]},
    ],
)
def test_schurter_rejects_malformed_country_filters(payload: object) -> None:
    with pytest.raises(DirectCompanyRequestError, match="country filters"):
        parse_country_filters(payload)


@pytest.mark.parametrize("mutation", ["country", "contact", "parent", "tag"])
def test_schurter_rejects_incomplete_or_non_swiss_records(mutation: str) -> None:
    record = deepcopy(job_record(1))
    if mutation == "country":
        record["fields"]["selectCountryISO"] = "DE"  # type: ignore[index]
    elif mutation == "contact":
        record["fields"]["contactMail"] = "jobs@attacker.example"  # type: ignore[index]
    elif mutation == "parent":
        record["fields"]["parentPage"]["fields"]["slug"] = "other"  # type: ignore[index]
    else:
        record["metadata"]["tags"] = []  # type: ignore[index]

    with pytest.raises(DirectCompanyRequestError, match="incomplete or non-Swiss"):
        parse_catalog_record(record, catalog_index=0)  # type: ignore[arg-type]


def test_schurter_rejects_duplicate_records_and_configured_limit() -> None:
    duplicate = job_record(1)

    def duplicate_handler(request: httpx.Request) -> httpx.Response:
        payload = (
            {"values": ["All", "CH"]}
            if request.url.path.endswith("/filters")
            else {"total": 2, "data": [duplicate, duplicate]}
        )
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        SchurterSwitzerlandJobsParser(transport=httpx.MockTransport(duplicate_handler)).search(
            LinkedInSearchRequest()
        )

    def limit_handler(request: httpx.Request) -> httpx.Response:
        payload = (
            {"values": ["All", "CH"]}
            if request.url.path.endswith("/filters")
            else {"total": 2, "data": [job_record(1), job_record(2)]}
        )
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        SchurterSwitzerlandJobsParser(
            max_jobs=1,
            transport=httpx.MockTransport(limit_handler),
        ).search(LinkedInSearchRequest())


def test_schurter_rejects_unstable_pagination_total() -> None:
    records = [job_record(index) for index in range(1, 11)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/filters"):
            payload: object = {"values": ["All", "CH"]}
        else:
            page = int(request.url.params["filters"].rsplit("=", 1)[-1])
            start = (page - 1) * 9
            payload = {
                "total": 10 if page == 1 else 11,
                "data": records[start : start + 9],
            }
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match="changed its total"):
        SchurterSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
            LinkedInSearchRequest()
        )


def test_schurter_wraps_api_request_failures() -> None:
    parser = SchurterSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_schurter_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["schurter_switzerland"]
    assert isinstance(parser, SchurterSwitzerlandJobsParser)
    assert parser.base_url == settings.schurter_switzerland_jobs_base_url
    assert parser.api_url == settings.schurter_switzerland_jobs_api_url
    assert parser.max_jobs == settings.schurter_switzerland_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SCHURTER", "filters": {}},
            "sources": ["schurter_switzerland", "schurter_switzerland"],
        }
    )
    assert request.sources == ["schurter_switzerland"]


def test_schurter_jobs_render_as_direct_company_imports() -> None:
    record = parse_catalog_record(job_record(1), catalog_index=0)
    job = normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"schurter_switzerland-{record['id']}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "SCHURTER AG import"
    assert stored["id"] == f"schurter_switzerland-{record['id']}"


def test_schurter_accepts_localized_gender_suffix_but_not_other_job() -> None:
    record = job_record(1, title="IMS & Documentation Manager (w/m/d)")
    record["fields"]["jobsCHMetadata"]["fields"]["title"] = "IMS & Documentation Manager (f/m/d)"
    assert parse_catalog_record(record, catalog_index=0)["title"] == record["fields"]["title"]
    record["fields"]["jobsCHMetadata"]["fields"]["title"] = "Different role (f/m/d)"
    with pytest.raises(DirectCompanyRequestError):
        parse_catalog_record(record, catalog_index=0)


def test_schurter_accepts_legacy_careers_parent_for_swiss_job() -> None:
    record = job_record(1)
    record["fields"]["parentPage"]["fields"].update(
        title="Offene Stellen", slug="ueber-uns/karriere/offene-stellen"
    )
    assert parse_catalog_record(record, catalog_index=0)["country"] == "CH"
