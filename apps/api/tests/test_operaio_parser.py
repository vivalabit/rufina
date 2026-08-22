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
from app.services.parsers.companies.operaio import (
    OperaioJobsParser,
    normalize_job,
    parse_catalog_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.operaio.ch/en/career"
CONTACT_URL = "https://www.operaio.ch/en/about-us"
HEAD_ID = "45dcc4d4-b1ad-4ca3-a0eb-45ab767bef63"
ITSM_ID = "e9124916-3f52-4809-a221-8aa47859e4f4"
ENGINEERING_ID = "2288d1a7-b59c-4c49-ac6b-6853cf64bfd0"


def cms_record(
    *,
    record_id: str,
    title: str,
    created_at: str,
    link: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "employmentType": "Hybrid",
        "_manualSort_39cb9e37-0d17-40a6-8ce8-48765416ade8": "6",
        "location": "Zürich Flughafen (ZH) oder Stettlen (BE)",
        "_id": record_id,
        "_owner": "ab91e375-84ec-41eb-9f53-2cf092efd364",
        "_createdDate": {"$date": created_at},
        "_updatedDate": {"$date": "2026-04-21T07:31:10.566Z"},
        "title": title,
        "workMode": "80 - 100%",
    }
    if link is not None:
        record["link"] = link
    return record


def official_records() -> dict[str, dict[str, object]]:
    return {
        HEAD_ID: cms_record(
            record_id=HEAD_ID,
            title="Head of Operations",
            created_at="2026-04-21T07:28:03.873Z",
            link=(
                "https://www.linkedin.com/jobs/view/4404033535/"
                "?refId=tracking&trackingId=campaign"
            ),
        ),
        ITSM_ID: cms_record(
            record_id=ITSM_ID,
            title="ITSM Consultant",
            created_at="2025-03-17T10:42:55.660Z",
        ),
        ENGINEERING_ID: cms_record(
            record_id=ENGINEERING_ID,
            title="Engineering Consultant",
            created_at="2025-03-17T10:42:52.254Z",
        ),
    }


def vacancy_card(*, record_id: str, title: str, location: str | None = None) -> str:
    return f"""
    <div id="comp-jobs__{record_id}" role="listitem"
         class="component wixui-repeater__item">
      <h4>{title}</h4>
      <p>{location or "Zürich Flughafen (ZH) oder Stettlen (BE)"}</p>
      <p>Hybrid</p>
      <p>80 - 100%</p>
      <a data-testid="linkElement" href="{CONTACT_URL}">Contact Us</a>
    </div>
    """


def catalog_html(
    records: dict[str, dict[str, object]],
    *,
    cards: list[str] | None = None,
    canonical: str = BASE_URL,
    site_name: str = "operaio.ch",
    business_name: str = "Operaio GmbH",
    contact_email: str = "customer@operaio.ch",
    warmup_override: object | None = None,
) -> str:
    viewer = {
        "siteFeaturesConfigs": {
            "seo": {"context": {"businessName": business_name}},
        }
    }
    warmup = (
        warmup_override
        if warmup_override is not None
        else {
            "appsWarmupData": {
                "dataBinding": {
                    "dataStore": {
                        "recordsByCollectionId": {"Career": records},
                    }
                }
            }
        }
    )
    rendered_cards = cards
    if rendered_cards is None:
        rendered_cards = [
            vacancy_card(
                record_id=record_id,
                title=str(record["title"]),
            )
            for record_id, record in records.items()
        ]
    return f"""
    <html lang="en">
      <head>
        <link rel="canonical" href="{canonical}">
        <meta property="og:site_name" content="{site_name}">
      </head>
      <body>
        <h1>Become an Operaio</h1>
        <h2>Why work with us</h2>
        <h2>Our open positions</h2>
        <section>{"".join(rendered_cards)}</section>
        <footer><a href="mailto:{contact_email}">{contact_email}</a></footer>
        <script id="wix-viewer-model" type="application/json">
          {json.dumps(viewer)}
        </script>
        <script id="wix-warmup-data" type="application/json">
          {json.dumps(warmup)}
        </script>
      </body>
    </html>
    """


def test_operaio_collects_complete_wix_catalog() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            text=catalog_html(official_records()),
            request=request,
        )

    result = OperaioJobsParser(
        transport=httpx.MockTransport(handler)
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [BASE_URL]
    assert result.message == (
        "Scanned 3 Operaio vacancies from the complete official Wix CMS catalog"
    )
    assert len(result.jobs) == 3
    head = result.jobs[0]
    assert head.source == "operaio"
    assert head.title == "Head of Operations"
    assert head.company == "Operaio GmbH"
    assert head.location == (
        "Zürich Flughafen (ZH) oder Stettlen (BE), Switzerland"
    )
    assert head.url == "https://www.linkedin.com/jobs/view/4404033535"
    assert head.apply_url == head.url
    assert head.posted_at == "2026-04-21T07:28:03.873Z"
    assert head.employment_type == "80–100% · Hybrid"
    assert head.description == (
        "Head of Operations\n"
        "Location: Zürich Flughafen (ZH) oder Stettlen (BE)\n"
        "Work arrangement: Hybrid\n"
        "Workload: 80–100%"
    )
    assert head.raw["id"] == HEAD_ID
    assert head.raw["catalog_index"] == 0
    assert head.raw["cms_record"]["link"].startswith("https://www.linkedin.com")

    itsm = result.jobs[1]
    assert itsm.title == "ITSM Consultant"
    assert itsm.url is None
    assert itsm.apply_url == (
        "mailto:customer@operaio.ch?subject=Application+for+ITSM+Consultant"
    )
    assert result.jobs[2].apply_url == (
        "mailto:customer@operaio.ch?subject=Application+for+Engineering+Consultant"
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            catalog_html(official_records(), site_name="attacker.example"),
            "invalid identity",
        ),
        (
            catalog_html(official_records(), business_name="Other GmbH"),
            "business identity",
        ),
        (
            catalog_html(official_records(), contact_email="jobs@attacker.example"),
            "contact email",
        ),
        (
            catalog_html(official_records(), warmup_override={}),
            "invalid CMS catalog",
        ),
    ],
)
def test_operaio_rejects_malformed_or_untrusted_catalogs(
    body: str,
    message: str,
) -> None:
    parser = OperaioJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=body, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_operaio_reconciles_visible_cards_with_cms_records() -> None:
    records = official_records()
    missing_card = [
        vacancy_card(record_id=HEAD_ID, title="Head of Operations"),
        vacancy_card(record_id=ITSM_ID, title="ITSM Consultant"),
    ]
    mismatched_card = [
        vacancy_card(record_id=HEAD_ID, title="Chief Executive Officer"),
        vacancy_card(record_id=ITSM_ID, title="ITSM Consultant"),
        vacancy_card(record_id=ENGINEERING_ID, title="Engineering Consultant"),
    ]

    with pytest.raises(DirectCompanyRequestError, match="visible cards"):
        parse_catalog_html(
            catalog_html(records, cards=missing_card),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_catalog_html(
            catalog_html(records, cards=mismatched_card),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )


def test_operaio_rejects_unsafe_application_link_and_catalog_over_limit() -> None:
    records = official_records()
    records[HEAD_ID]["link"] = "https://attacker.example/jobs/4404033535"
    with pytest.raises(DirectCompanyRequestError, match="unsafe application link"):
        parse_catalog_html(
            catalog_html(records),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=100,
        )

    records = official_records()
    with pytest.raises(DirectCompanyRequestError, match="configured limit"):
        parse_catalog_html(
            catalog_html(records),
            page_url=BASE_URL,
            expected_url=BASE_URL,
            max_jobs=2,
        )


def test_operaio_wraps_catalog_request_failures() -> None:
    parser = OperaioJobsParser(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_operaio_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["operaio"]
    assert isinstance(parser, OperaioJobsParser)
    assert parser.base_url == settings.operaio_jobs_base_url
    assert parser.max_jobs == settings.operaio_jobs_max_jobs

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Operaio", "filters": {}},
            "sources": ["operaio", "operaio"],
        }
    )
    assert request.sources == ["operaio"]


def test_operaio_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": ITSM_ID,
        "title": "ITSM Consultant",
        "company": "Operaio GmbH",
        "location": "Zürich Flughafen (ZH) oder Stettlen (BE), Switzerland",
        "arrangement": "Hybrid",
        "workload": "80–100%",
        "apply_url": (
            "mailto:customer@operaio.ch?subject=Application+for+ITSM+Consultant"
        ),
    }
    job = normalize_job(record)
    stored = parsed_job_to_stored_job(
        job,
        job_id=f"operaio-{ITSM_ID}",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Operaio GmbH import"
    assert stored["id"] == f"operaio-{ITSM_ID}"
