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
from app.services.parsers.companies.loewenfels import (
    LOEWENFELS_API_URL,
    LoewenfelsJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.loewenfels.test/karriere/"
API_URL = (
    "https://odm.ostendis.com/ojp/data/v55/jobs/"
    "e093bfef1e5b4b119ddf2f3eb38e665e/DE?domain=www.loewenfels.ch"
)
TOKEN = "i7fkjc4g4s8w5hushyko5jakgml0wibdzdygnhb6wd96vjm7p0of6eeq4ev9h1cp"
SECOND_TOKEN = "4spcscmr3owla8l7o1uc2vbo1osesdo7q1yslwvbwkanleyphy7f0a3h5iqq357f"
DETAIL_URL = f"https://jobs.loewenfels.ch/publication/senior-account-manager/{TOKEN}"
SECOND_DETAIL_URL = "https://jobs.loewenfels.ch/publication/product-owner/" + SECOND_TOKEN
APPLY_URL = f"https://jobs.loewenfels.ch/cvdropper/eeda6dc0cbc1426298099e9c72d7650b/DE?src={TOKEN}"
SECOND_APPLY_URL = (
    f"https://jobs.loewenfels.ch/cvdropper/b2a9701883644b6f9525f827733de89e/DE?src={SECOND_TOKEN}"
)
SPONTANEOUS_URL = (
    "https://jobs.loewenfels.ch/ojp/#!/cvdropper/"
    "d510703ab7ab4a35a6f136e7055a4ac5/DE?src="
    "kotwdk5yt5njfyy7m6mzp5l254glcsd6lph6kxfyyc0tzjiofpnftf7i6ht4sqqi"
)


def careers_html(
    *,
    token: str = "e093bfef1e5b4b119ddf2f3eb38e665e",
    company: str = "Löwenfels Partner AG",
) -> str:
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "url": "https://www.loewenfels.ch",
                "name": "Löwenfels - Swiss Software Built to Last",
            }
        ],
    }
    return f"""
    <html lang="de-CH">
      <head>
        <link rel="canonical" href="{BASE_URL}">
        <meta property="og:url" content="{BASE_URL}">
        <script type="application/ld+json">{json.dumps(schema)}</script>
      </head>
      <body>
        <header>
          <img class="custom-logo" data-src="https://www.loewenfels.ch/wp-content/uploads/2025/08/loewenfels-logo-claim-rgb.svg">
        </header>
        <main>
          <h1>Karriere</h1><h2>Offene Stellen</h2>
          <script id="ostendisLoader"
            src="https://odm.ostendis.com/ojp/assets/loader"
            data-token="{token}"></script>
          <div id="ostendisJobs"></div>
          <script>
            OSTENDISJOBS.embed("{token}", "DE", "#ostendisJobs", {{}});
          </script>
          <a href="{SPONTANEOUS_URL}">Spontanbewerbung senden</a>
        </main>
        <footer>
          {company}<br>Maihofstrasse 1<br>CH – 6004 Luzern<br>
          +41 41 418 44 00<br>info@loewenfels.ch
        </footer>
      </body>
    </html>
    """


def listing_record(
    *,
    job_id: int = 76584,
    title: str = "Senior Account Manager ",
    token: str = TOKEN,
    slug: str = "senior-account-manager",
    country_code: str = "",
    city: str = "",
    workload: str = "100%",
    action: str = "",
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "countrycode": country_code,
        "city": city,
        "zip": "6004" if city else "",
        "published": "",
        "workload": workload,
        "detail": f"https://jobs.loewenfels.ch/publication/{slug}/{token}",
        "action": action,
        "position": "",
        "language": "Deutsch",
        "langcode": "DE",
    }


def catalog_payload(records: list[dict[str, object]]) -> dict[str, object]:
    return {"jobs": records, "error": {"message": ""}, "options": {"page": 25}}


def detail_html(
    *,
    title: str = "Senior Account Manager",
    apply_url: str = APPLY_URL,
    company: str = "Löwenfels Partner AG",
    country: str = "CH",
    posted_at: str = "2026-08-07",
    employment_type: list[str] | None = None,
) -> str:
    schema = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": (
            "<h1>Senior Account Manager (a)</h1>"
            "<p>Wir entwickeln langlebige Software für Schweizer Behörden.</p>"
            "<h3>Das machst du bei uns</h3>"
            "<ul><li>Du entwickelst unsere Kundenbeziehungen.</li></ul>"
            f'<a href="{apply_url}">Jetzt Bewerbung senden</a>'
        ),
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": "1425",
        },
        "datePosted": posted_at,
        "employmentType": employment_type or ["FULL_TIME", "FULL_TIME"],
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Maihofstrasse 1",
                "addressLocality": "Luzern",
                "postalCode": "6004",
                "addressCountry": country,
            },
        },
    }
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'


def second_record() -> dict[str, object]:
    return listing_record(
        job_id=31751,
        title="Product Owner (a)",
        token=SECOND_TOKEN,
        slug="product-owner",
        country_code="CH",
        city="Luzern",
        workload="80 - 100%",
    )


def handler_for(
    records: list[dict[str, object]],
    *,
    first_detail: str | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.loewenfels.test":
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(200, json=catalog_payload(records), request=request)
        if request.url.path.endswith(TOKEN):
            return httpx.Response(
                200,
                text=first_detail or detail_html(),
                request=request,
            )
        return httpx.Response(
            200,
            text=detail_html(
                title="Product Owner (a)",
                apply_url=SECOND_APPLY_URL,
                posted_at="2023-09-11",
                employment_type=["PART_TIME", "FULL_TIME"],
            ),
            request=request,
        )

    return handler


def test_loewenfels_collects_complete_catalog_with_details() -> None:
    result = LoewenfelsJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler_for([listing_record(), second_record()])),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert result.status == "completed"
    assert result.message == ("Scanned 2 Löwenfels Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2
    first, second = result.jobs
    assert first.source == "loewenfels"
    assert first.title == "Senior Account Manager"
    assert first.company == "Löwenfels Partner AG"
    assert first.location == "6004 Luzern, Switzerland"
    assert first.url == DETAIL_URL
    assert first.apply_url == APPLY_URL
    assert first.posted_at == "2026-08-07"
    assert first.employment_type == "Full-time · 100%"
    assert first.description and "langlebige Software" in first.description
    assert second.url == SECOND_DETAIL_URL
    assert second.apply_url == SECOND_APPLY_URL
    assert second.employment_type == "Part-time / Full-time · 80–100%"


def test_loewenfels_preserves_catalog_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.loewenfels.test":
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.host == "odm.ostendis.com":
            return httpx.Response(
                200,
                json=catalog_payload([listing_record()]),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        LoewenfelsJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior Account Manager"
    assert job.url == DETAIL_URL
    assert job.apply_url == DETAIL_URL
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_loewenfels_rejects_wrong_career_identity_or_portal() -> None:
    def run(page: str) -> None:
        LoewenfelsJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="identity or job portal"):
        run(careers_html(token="00000000000000000000000000000000"))
    with pytest.raises(DirectCompanyRequestError, match="identity or job portal"):
        run(careers_html(company="Attacker AG"))


def test_loewenfels_rejects_invalid_catalog_records() -> None:
    def run(record: dict[str, object]) -> None:
        LoewenfelsJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler_for([record])),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        run(listing_record(country_code="DE", city="Berlin"))
    with pytest.raises(DirectCompanyRequestError, match="non-Swiss vacancy"):
        run(listing_record(action="https://attacker.example/apply"))
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        LoewenfelsJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(handler_for([listing_record(), listing_record()])),
        ).search(LinkedInSearchRequest())


def test_loewenfels_rejects_mismatched_detail_but_keeps_catalog() -> None:
    job = (
        LoewenfelsJobsParser(
            base_url=BASE_URL,
            api_url=API_URL,
            transport=httpx.MockTransport(
                handler_for(
                    [listing_record()],
                    first_detail=detail_html(company="Attacker AG", country="DE"),
                )
            ),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.apply_url == DETAIL_URL
    assert job.description is None
    assert "mismatched vacancy" in str(job.raw["detail_error"])


def test_loewenfels_accepts_empty_catalog_and_wraps_request_failures() -> None:
    result = LoewenfelsJobsParser(
        base_url=BASE_URL,
        api_url=API_URL,
        transport=httpx.MockTransport(handler_for([])),
    ).search(LinkedInSearchRequest())
    assert result.jobs == []

    parser = LoewenfelsJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_loewenfels_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["loewenfels"]
    assert isinstance(parser, LoewenfelsJobsParser)
    assert parser.base_url == settings.loewenfels_jobs_base_url
    assert parser.api_url == LOEWENFELS_API_URL
    assert parser.detail_workers == settings.loewenfels_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Löwenfels", "filters": {}},
            "sources": ["loewenfels", "loewenfels"],
        }
    )
    assert request.sources == ["loewenfels"]

    job = normalize_job(
        {
            "id": "76584",
            "title": "Senior Account Manager",
            "url": DETAIL_URL,
            "workload": "100%",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="loewenfels-76584",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Löwenfels Partner AG import"
    assert stored["id"] == "loewenfels-76584"
