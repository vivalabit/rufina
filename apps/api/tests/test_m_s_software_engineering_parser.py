from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.m_s_software_engineering import (
    M_S_API_URL,
    MSSoftwareEngineeringJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.m-s.test/karriere/offene-stellen/"
FIRST_FEED_HANDLE = "e7m43cjkbae7l8ftlllb7shk58v80pw"
SECOND_FEED_HANDLE = "uohrqoce15yraz0cj3h7rsagsaplqyi"
FIRST_PUBLIC_HANDLE = "tdpbva0dmo30ygekla6ndzjncmpo7b"
SECOND_PUBLIC_HANDLE = "v82sy2mofvqsbpaebdguxcjozbogkx"
YOUSTY_URL = (
    "https://www.yousty.ch/de-CH/lehrstellen/profile/"
    "12691918-informatiker-in-efz-plattformentwicklung-schlieren-zh-"
    "m-s-software-engineering-ag"
)


def job_record(
    *,
    title: str = "Softwareentwickler/-in .NET/C# (80-100%)",
    feed_handle: str = FIRST_FEED_HANDLE,
    public_handle: str = FIRST_PUBLIC_HANDLE,
    published_at: str = "2026-07-21",
    remote: str | None = None,
) -> dict[str, object]:
    return {
        "title": title,
        "handle": feed_handle,
        "shortHandle": "dbythhbo" if feed_handle == FIRST_FEED_HANDLE else "p1jojft1",
        "showUrl": f"https://m-s.onlyfy.jobs/job/{public_handle}",
        "applyUrl": f"https://m-s.onlyfy.jobs/application/apply/{public_handle}",
        "department": {"id": 9, "title": "IT und Softwareentwicklung"},
        "city": {
            "id": 163828,
            "title": "Schlieren",
            "country": "Schweiz",
            "countryCode": "CH",
            "zip_code": "8952",
        },
        "positionType": {"id": 9, "title": "Teilzeit / Vollzeit"},
        "seniority": {"id": 3, "title": "Berufserfahren"},
        "published_at": published_at,
        "remote": remote,
        "simple_html_content": (
            f"<h2>{title}</h2><h4>Was du tust</h4>"
            "<ul><li>Du entwickelst nachhaltige Softwarelösungen.</li></ul>"
        ),
        "metaDescription": f"Kurzbeschreibung für {title}",
        "applications_deadline_information": {
            "applications_allowed": True,
            "stop_applications_at": None,
        },
    }


def apprenticeship_record() -> dict[str, str]:
    return {
        "city": "Schlieren",
        "img": "/img/tiles/lehrstelle-plattformentwicklung.webp",
        "text": "Lehrstelle als Informatiker/in EFZ Plattformentwicklung ab 2027.",
        "title": "Informatiker/in EFZ Plattformentwicklung",
        "url": YOUSTY_URL,
        "video": "https://www.youtube.com/watch?v=example",
    }


def schema_for(record: dict[str, object]) -> dict[str, object]:
    city = record["city"]
    assert isinstance(city, dict)
    return {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": record["title"],
        "description": record["simple_html_content"],
        "identifier": {
            "@type": "PropertyValue",
            "name": "M&S Software Engineering AG",
            "value": record["handle"],
        },
        "datePosted": record["published_at"],
        "hiringOrganization": {
            "@type": "Organization",
            "name": "M&S Software Engineering AG",
            "sameAs": "https://www.m-s.ch/",
            "logo": "https://www.m-s.ch/img/brand-logo.svg",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": city["title"],
                "postalCode": city["zip_code"],
                "addressCountry": "CH",
            },
        },
        "employmentType": ["FULL_TIME", "PART_TIME"],
    }


def careers_html(
    records: list[dict[str, object]],
    *,
    apprenticeships: list[dict[str, str]] | None = None,
    canonical: str = BASE_URL,
    company: str = "M&S Software Engineering AG",
) -> str:
    organization = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "name": company,
                "legalName": company,
                "url": "https://www.m-s.ch/",
                "logo": "https://www.m-s.ch/img/brand-logo.svg",
                "email": "info@m-s.ch",
                "telephone": "+41 44 738 19 19",
                "location": [
                    {
                        "@type": "Place",
                        "address": {
                            "addressLocality": "Bern",
                            "postalCode": "3014",
                        },
                    },
                    {
                        "@type": "Place",
                        "address": {
                            "addressLocality": "Schlieren",
                            "postalCode": "8952",
                        },
                    },
                ],
            }
        ],
    }
    baked = [
        {
            "bannerUrl": "https://content.onlyfy.net/banner.png",
            "city": record["city"]["title"],
            "handle": record["handle"],
            "href": record["showUrl"],
            "metaDescription": record["metaDescription"],
            "title": record["title"],
        }
        for record in records
    ]
    schemas = "".join(
        f'<script type="application/ld+json">{json.dumps(schema_for(record))}</script>'
        for record in records
    )
    apprenticeship_payload = (
        [apprenticeship_record()] if apprenticeships is None else apprenticeships
    )
    apprenticeship_json = json.dumps(apprenticeship_payload)
    return f"""
    <html lang="de"><head>
      <title>Offene Stellen | M&amp;S Software Engineering AG</title>
      <link rel="canonical" href="{canonical}">
      <script type="application/ld+json">{json.dumps(organization)}</script>
    </head><body><main>
      <header>Offene Stellen</header>
      <div id="msui-jobs-feed" data-jobs-feed-url="{M_S_API_URL}">
        <h3>Schlieren (ZH)</h3><h3>Bern Wankdorf</h3>
      </div>
      <script type="application/json" id="msui-jobs-feed-baked">{json.dumps(baked)}</script>
      <script type="application/json" id="msui-lehrstellen-baked">{apprenticeship_json}</script>
      {schemas}
    </main><footer>
      Bern Wankdorf | Schlieren (ZH) | info [at] m-s.ch | +41 44 738 19 19
    </footer></body></html>
    """


def api_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "company": "M&S Software Engineering AG",
        "totalResults": len(records),
        "currentStartDisplay": 0,
        "jobs": records,
    }


def parser_for(
    records: list[dict[str, object]],
    *,
    page_records: list[dict[str, object]] | None = None,
    apprenticeships: list[dict[str, str]] | None = None,
) -> MSSoftwareEngineeringJobsParser:
    page_records = records if page_records is None else page_records

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.m-s.test":
            return httpx.Response(
                200,
                text=careers_html(page_records, apprenticeships=apprenticeships),
                request=request,
            )
        return httpx.Response(200, json=api_payload(records), request=request)

    return MSSoftwareEngineeringJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )


def test_m_s_collects_onlyfy_jobs_and_external_apprenticeship() -> None:
    records = [
        job_record(),
        job_record(
            title="AKIS Produktberater/-in (Renten / FAK)",
            feed_handle=SECOND_FEED_HANDLE,
            public_handle=SECOND_PUBLIC_HANDLE,
            published_at="2026-07-22",
            remote="office_and_remote",
        ),
    ]
    result = parser_for(records).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 M&S Switzerland vacancies from 2 Onlyfy records and 1 apprenticeship listings"
    )
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "m_s_software_engineering"
    assert first.title == "Softwareentwickler/-in .NET/C# (80-100%)"
    assert first.company == "M&S Software Engineering AG"
    assert first.location == "8952 Schlieren, Switzerland"
    assert first.url == f"https://m-s.onlyfy.jobs/job/{FIRST_PUBLIC_HANDLE}"
    assert first.apply_url == (f"https://m-s.onlyfy.jobs/application/apply/{FIRST_PUBLIC_HANDLE}")
    assert first.posted_at == "2026-07-21"
    assert first.employment_type == "Part-time / Full-time · 80–100%"
    assert first.seniority == "Berufserfahren"
    assert "Du entwickelst nachhaltige Softwarelösungen." in (first.description or "")

    apprenticeship = result.jobs[2]
    assert apprenticeship.title == "Informatiker/in EFZ Plattformentwicklung"
    assert apprenticeship.url == YOUSTY_URL
    assert apprenticeship.apply_url == YOUSTY_URL
    assert apprenticeship.employment_type == "Apprenticeship"
    assert apprenticeship.raw["id"] == "yousty-12691918"


def test_m_s_accepts_a_genuinely_empty_catalog() -> None:
    result = parser_for([], apprenticeships=[]).search(LinkedInSearchRequest())
    assert result.jobs == []
    assert result.message == (
        "Scanned 0 M&S Switzerland vacancies from 0 Onlyfy records and 0 apprenticeship listings"
    )


def test_m_s_rejects_wrong_career_identity() -> None:
    record = job_record()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.m-s.test":
            return httpx.Response(
                200,
                text=careers_html([record], company="Lookalike AG"),
                request=request,
            )
        return httpx.Response(200, json=api_payload([record]), request=request)

    parser = MSSoftwareEngineeringJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())


def test_m_s_rejects_mismatched_or_non_swiss_onlyfy_records() -> None:
    page_record = job_record()
    changed_title = deepcopy(page_record)
    changed_title["title"] = "Different vacancy"
    with pytest.raises(DirectCompanyRequestError, match="incomplete or mismatched"):
        parser_for([changed_title], page_records=[page_record]).search(LinkedInSearchRequest())

    foreign = deepcopy(page_record)
    assert isinstance(foreign["city"], dict)
    foreign["city"]["countryCode"] = "DE"
    with pytest.raises(DirectCompanyRequestError, match="incomplete or mismatched"):
        parser_for([foreign], page_records=[page_record]).search(LinkedInSearchRequest())


def test_m_s_rejects_invalid_apprenticeship_and_wraps_http_errors() -> None:
    invalid = apprenticeship_record()
    invalid["url"] = "https://evil.test/job/12691918"
    with pytest.raises(DirectCompanyRequestError, match="apprenticeship catalog"):
        parser_for([], apprenticeships=[invalid]).search(LinkedInSearchRequest())

    parser = MSSoftwareEngineeringJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_m_s_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["m_s_software_engineering"]
    assert isinstance(parser, MSSoftwareEngineeringJobsParser)
    assert parser.base_url == settings.m_s_software_engineering_jobs_base_url
    assert parser.api_url == M_S_API_URL

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "M&S", "filters": {}},
            "sources": ["m_s_software_engineering", "m_s_software_engineering"],
        }
    )
    assert request.sources == ["m_s_software_engineering"]

    job = normalize_job(
        {
            "id": FIRST_PUBLIC_HANDLE,
            "title": "Softwareentwickler/-in .NET/C# (80-100%)",
            "url": f"https://m-s.onlyfy.jobs/job/{FIRST_PUBLIC_HANDLE}",
            "apply_url": (f"https://m-s.onlyfy.jobs/application/apply/{FIRST_PUBLIC_HANDLE}"),
            "location": {"title": "Schlieren", "zip_code": "8952"},
            "position_type_text": "Teilzeit / Vollzeit",
            "seniority_text": "Berufserfahren",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"m_s_software_engineering-{FIRST_PUBLIC_HANDLE}",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "M&S Software Engineering AG import"
    assert stored["id"] == f"m_s_software_engineering-{FIRST_PUBLIC_HANDLE}"
