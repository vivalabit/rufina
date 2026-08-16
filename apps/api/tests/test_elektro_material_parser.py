from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.elektro_material import (
    ElektroMaterialJobsParser,
    titles_match,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://elektro-material.ch/de/cms/seite/offene-stellen-t33143s226453a4614994"
CMS_URL = "https://elektro-material.test/emwebservices/v2/elektromaterial/cms/pages"
SMART_URL = "https://api.smartrecruiters.test/v1/companies/REXEL1/postings"


def main_slot(components: list[dict[str, object]]) -> dict[str, object]:
    return {
        "contentSlots": {
            "contentSlot": [
                {
                    "position": "MainContent",
                    "components": {"component": components},
                }
            ]
        }
    }


def listing_component(
    slug: str,
    title: str,
    *,
    uid: str,
    location: str = "Zürich",
) -> dict[str, object]:
    return {
        "uid": uid,
        "typeCode": "CMSParagraphComponent",
        "modifiedtime": "2026-07-24T09:22:35+02:00",
        "content": (
            f"<h3>{title}</h3><p>Standort {location}<br>"
            f'<a href="/de/cms/seite/{slug}">Mehr erfahren</a></p>'
        ),
    }


def catalog_payload(components: list[dict[str, object]]) -> dict[str, object]:
    return {
        "uid": "cmsitem_00089040",
        "title": "Jobs und Karriere : Offene Stellen",
        "typeCode": "EMCorporateContentPage2",
        **main_slot(
            [
                {
                    "uid": "intro",
                    "typeCode": "CMSParagraphComponent",
                    "content": "<h2>Offene Stellen</h2>",
                },
                {
                    "uid": "back-link",
                    "typeCode": "CMSParagraphComponent",
                    "content": (
                        '<p><a href="/de/cms/seite/jobs-und-karriere">Zurück zur Übersicht</a></p>'
                    ),
                },
                *components,
            ]
        ),
    }


def detail_payload(
    title: str,
    publication_uuid: str,
    *,
    location: str = "Zürich",
) -> dict[str, object]:
    return {
        "uid": "detail-page",
        "title": title,
        "description": title,
        "typeCode": "EMCorporateContentPage2",
        **main_slot(
            [
                {
                    "uid": "description",
                    "typeCode": "CMSParagraphComponent",
                    "content": (
                        f"<p>Für den Standort {location} suchen wir dich.</p>"
                        f"<h1>{title}</h1><h3>Stellenbeschreibung</h3>"
                        "<p>Gestalte die Zukunft von Elektro-Material.</p>"
                    ),
                },
                {
                    "uid": "apply",
                    "typeCode": "CMSButtonComponent",
                    "title": "Jetzt bewerben",
                    "newTab": "true",
                    "localizedUrl": (
                        "https://jobs.smartrecruiters.com/oneclick-ui/company/"
                        f"REXEL1/publication/{publication_uuid}?dcr_ci=REXEL1"
                    ),
                },
            ]
        ),
    }


def smartrecruiters_payload(
    job_id: int,
    publication_uuid: str,
    title: str,
    *,
    location: str = "Zürich",
) -> dict[str, object]:
    return {
        "id": str(job_id),
        "uuid": publication_uuid,
        "name": title,
        "refNumber": "REF6756Q",
        "company": {"name": "REXEL", "identifier": "REXEL1"},
        "location": {
            "city": location,
            "region": "ZH",
            "country": "ch",
            "fullLocation": f"{location}, Switzerland",
        },
        "customField": [
            {"fieldLabel": "Legal Entity", "valueLabel": "ELEKTRO-MATERIAL AG"},
            {"fieldLabel": "Country/Region", "valueLabel": "Switzerland"},
            {"fieldLabel": "Brands", "valueLabel": "Elektro-Material AG"},
            {"fieldLabel": "Employment Type", "valueLabel": "Full-time"},
        ],
        "releasedDate": "2026-07-23T12:01:19.349Z",
        "postingUrl": (
            f"https://jobs.smartrecruiters.com/REXEL1/{job_id}-"
            "ict-system-spezialist-in-network-engineer-100-"
        ),
        "active": True,
        "visibility": "PUBLIC",
        "experienceLevel": {"label": "Associate"},
        "typeOfEmployment": {"label": "Full-time"},
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "title": "Unternehmensbeschreibung",
                    "text": "<p>Elektro-Material ist Teil der Rexel-Gruppe.</p>",
                },
                "jobDescription": {
                    "title": "Stellenbeschreibung",
                    "text": "<p>Gestalte die Zukunft.</p><ul><li>Betreue Systeme.</li></ul>",
                },
            }
        },
    }


def test_elektro_material_scans_complete_catalog_and_enriches_jobs() -> None:
    first_uuid = "e05255c1-009c-400e-9a1f-4c6866a0ec18"
    second_uuid = "a05255c1-009c-400e-9a1f-4c6866a0ec19"
    jobs = {
        "ict-system-spezialist-in-network-engineer-100": (
            "ICT System Spezialist:in / Network Engineer 100 %",
            "Zürich",
            first_uuid,
            744000139266729,
        ),
        "logistiker-in-100-": (
            "Logistiker/in 100%",
            "Bern",
            second_uuid,
            744000139266730,
        ),
    }
    catalog = catalog_payload(
        [
            listing_component(slug, title, uid=f"card-{index}", location=location)
            for index, (slug, (title, location, _, _)) in enumerate(jobs.items(), start=1)
        ]
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "elektro-material.test":
            page_id = request.url.params["pageLabelOrId"]
            assert request.url.params["lang"] == "de"
            assert request.url.params["curr"] == "CHF"
            if page_id == "offene-stellen-t33143s226453a4614994":
                return httpx.Response(200, json=catalog, request=request)
            title, location, publication_uuid, _ = jobs[page_id]
            return httpx.Response(
                200,
                json=detail_payload(title, publication_uuid, location=location),
                request=request,
            )
        publication_uuid = request.url.path.rsplit("/", maxsplit=1)[-1]
        title, location, _, job_id = next(
            value for value in jobs.values() if value[2] == publication_uuid
        )
        return httpx.Response(
            200,
            json=smartrecruiters_payload(job_id, publication_uuid, title, location=location),
            request=request,
        )

    result = ElektroMaterialJobsParser(
        base_url=BASE_URL,
        cms_api_url=CMS_URL,
        smartrecruiters_api_url=SMART_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert len(result.jobs) == 2
    assert result.message == ("Scanned 2 Elektro-Material vacancies from 2 CMS catalog records")
    assert len(requests) == 5
    job = result.jobs[0]
    assert job.source == "elektro_material"
    assert job.title == "ICT System Spezialist:in / Network Engineer 100 %"
    assert job.company == "Elektro-Material AG"
    assert job.location == "Zürich, Switzerland"
    assert job.url == (
        "https://jobs.smartrecruiters.com/REXEL1/744000139266729-"
        "ict-system-spezialist-in-network-engineer-100-"
    )
    assert job.apply_url == (
        "https://jobs.smartrecruiters.com/oneclick-ui/company/REXEL1/"
        f"publication/{first_uuid}?dcr_ci=REXEL1"
    )
    assert job.posted_at == "2026-07-23"
    assert job.employment_type == "Full-time"
    assert job.seniority == "Associate"
    assert job.description == (
        "Unternehmensbeschreibung\n\n"
        "Elektro-Material ist Teil der Rexel-Gruppe.\n\n"
        "Stellenbeschreibung\n\nGestalte die Zukunft.\n- Betreue Systeme."
    )
    assert job.raw["detail"]["id"] == "744000139266729"
    assert job.raw["detail"]["cms"]["apply_component_uid"] == "apply"
    assert job.raw["total_available"] == 2


def test_elektro_material_preserves_listing_when_detail_fails() -> None:
    title = "EDI-Manager in Digital Commerce 60%"
    catalog = catalog_payload(
        [listing_component("edi-manager-in-digital-commerce-60", title, uid="card")]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("pageLabelOrId") == "offene-stellen-t33143s226453a4614994":
            return httpx.Response(200, json=catalog, request=request)
        return httpx.Response(503, request=request)

    job = (
        ElektroMaterialJobsParser(
            base_url=BASE_URL,
            cms_api_url=CMS_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == title
    assert job.location == "Zürich, Switzerland"
    assert job.url == (
        "https://elektro-material.ch/de/cms/seite/edi-manager-in-digital-commerce-60"
    )
    assert job.apply_url is None
    assert job.posted_at is None
    assert job.employment_type == "60%"
    assert "503" in job.raw["detail_error"]


@pytest.mark.parametrize(
    ("smartrecruiters_title", "listing_title"),
    [
        ("EDI-Manager in Digital Commerce, 60%", "EDI-Manager in Digital Commerce 60%"),
        ("Leiter/in Category Management", "Leiter/in Category Management 100%"),
    ],
)
def test_elektro_material_accepts_smartrecruiters_workload_title_variants(
    smartrecruiters_title: str,
    listing_title: str,
) -> None:
    assert titles_match(smartrecruiters_title, listing_title)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (catalog_payload([]), "did not expose any vacancies"),
        (
            catalog_payload(
                [
                    listing_component("same-job", "Job", uid="one"),
                    listing_component("same-job", "Job", uid="two"),
                ]
            ),
            "duplicate vacancies",
        ),
        ({"title": "Wrong"}, "unexpected page"),
    ],
)
def test_elektro_material_rejects_invalid_catalogs(
    payload: dict[str, object], message: str
) -> None:
    parser = ElektroMaterialJobsParser(
        cms_api_url=CMS_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_elektro_material_enforces_limit_and_wraps_http_errors() -> None:
    catalog = catalog_payload(
        [
            listing_component("first", "First job", uid="one"),
            listing_component("second", "Second job", uid="two"),
        ]
    )
    too_large = ElektroMaterialJobsParser(
        cms_api_url=CMS_URL,
        max_catalog_records=1,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=catalog, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="above the configured limit"):
        too_large.search(LinkedInSearchRequest())

    unavailable = ElektroMaterialJobsParser(
        cms_api_url=CMS_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        unavailable.search(LinkedInSearchRequest())


def test_elektro_material_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["elektro_material"]
    assert isinstance(parser, ElektroMaterialJobsParser)
    assert parser.cms_api_url == settings.elektro_material_jobs_cms_api_url
    assert parser.smartrecruiters_api_url == settings.elektro_material_jobs_smartrecruiters_api_url
    assert parser.max_catalog_records == settings.elektro_material_jobs_max_catalog_records

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Elektro-Material", "filters": {}},
            "sources": ["elektro_material", "elektro_material"],
        }
    )
    assert request.sources == ["elektro_material"]


def test_elektro_material_jobs_render_as_direct_company_imports() -> None:
    job = ElektroMaterialJobsParser().normalize_job(
        {
            "slug": "edi-manager-in-digital-commerce-60",
            "title": "EDI-Manager in Digital Commerce 60%",
            "location": "Zürich, Switzerland",
            "url": ("https://elektro-material.ch/de/cms/seite/edi-manager-in-digital-commerce-60"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="elektro_material-744000139266729",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Elektro-Material AG import"
    assert stored["company"] == "Elektro-Material AG"
    assert stored["id"] == "elektro_material-744000139266729"
