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
from app.services.parsers.companies.webtouch import WebtouchJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.webtouch.ch/karriere"
INDEX_URL = "https://framerusercontent.com/sites/2WjhjUxJ9kIXVbLcaJgzys/searchIndex-test.json"
SLUGS = ("call-agent-in-b2b-outbound", "sales-development-representative")
TITLES = (
    "Call Agent/in B2B Outbound (Remote)",
    "Sales Development Representative",
)


def careers_html() -> str:
    return f"""
    <html lang="de-CH"><head>
      <link rel="canonical" href="{BASE_URL}">
      <meta property="og:title" content="Jobs im B2B Sales | Webtouch">
      <meta name="framer-search-index" content="{INDEX_URL}">
    </head><body></body></html>
    """


def search_index(count: int = 2) -> dict[str, object]:
    payload: dict[str, object] = {
        "/karriere": {
            "version": 1,
            "title": "Jobs im B2B Sales | Webtouch",
            "h1": ["Werde Teil von Webtouch"],
        }
    }
    for index in range(count):
        payload[f"/karriere/{SLUGS[index]}"] = {
            "version": 1,
            "title": f"{TITLES[index]} - Full-Time - Remote | Webtouch",
            "h1": [TITLES[index]],
            "p": ["Public vacancy content"],
        }
    return payload


def richtext(*blocks: object) -> str:
    return json.dumps([1, *blocks])


def detail_html(index: int) -> str:
    slug = SLUGS[index]
    title = TITLES[index]
    query = {
        "from": "785ffcb3-5518-43b8-bdca-466fd59a652e",
        "select": [
            {"collection": "vq0ovXxlM", "name": name, "type": "Identifier"}
            for name in (
                "zOsEvNQTi",
                "aBacXVXtF",
                "fREawOuR4",
                "piAkN6KRo",
                "pK8IqAeG0",
                "J8bgVqu4U",
            )
        ],
        "where": {
            "right": {"type": "LiteralValue", "value": slug},
        },
    }
    handover = [
        {},
        ["Map", 2, 3],
        f"{json.dumps(query)}default",
        [4],
        {
            "zOsEvNQTi": 5,
            "aBacXVXtF": 8,
            "fREawOuR4": 13,
            "piAkN6KRo": 15,
            "pK8IqAeG0": 18,
            "J8bgVqu4U": 21,
        },
        {"type": 6, "value": 7},
        "string",
        title,
        {"type": 9, "value": 10},
        "richtext",
        {"collectionId": 11, "pointer": 12},
        "collection-default",
        richtext(
            [4, "p", None, [4, "strong", None, [5, "Eine Stimme, die Türen öffnet."]]],
            [4, "p", None, [5, "Dann lies weiter."]],
        ),
        {"type": 6, "value": 14},
        "Remote",
        {"type": 16, "value": 17},
        "enum",
        "pzCRQk_30",
        {"type": 9, "value": 19},
        {"collectionId": 11, "pointer": 20},
        richtext(
            [4, "p", None, [4, "strong", None, [5, "Deine Aufgaben:"]]],
            [
                4,
                "ul",
                None,
                [4, "li", None, [4, "p", None, [5, "Schweizer KMU anrufen"]]],
                [4, "li", None, [4, "p", None, [5, "Termine im CRM erfassen"]]],
            ],
        ),
        {"type": 22, "value": 23},
        "link",
        (
            f"https://join.com/companies/webtouchch/{15474250 + index}"
            "?utm_medium=social_sharing&utm_source=copy_link"
        ),
    ]
    url = f"{BASE_URL}/{slug}"
    return f"""
    <html lang="de-CH"><head><link rel="canonical" href="{url}"></head><body>
      <script type="framer/handover" id="__framer__handoverData">{json.dumps(handover)}</script>
    </body></html>
    """


def test_webtouch_discovers_full_index_and_parses_framer_cms_details() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if str(request.url) == INDEX_URL:
            return httpx.Response(200, json=search_index(), request=request)
        index = SLUGS.index(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, text=detail_html(index), request=request)

    result = WebtouchJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requests == [
        BASE_URL,
        INDEX_URL,
        f"{BASE_URL}/{SLUGS[0]}",
        f"{BASE_URL}/{SLUGS[1]}",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Webtouch vacancies from the official Framer catalog")
    assert len(result.jobs) == 2

    job = result.jobs[0]
    assert job.source == "webtouch"
    assert job.title == TITLES[0]
    assert job.company == "Webtouch GmbH"
    assert job.location == "Remote"
    assert job.url == f"{BASE_URL}/{SLUGS[0]}"
    assert job.apply_url == "https://join.com/companies/webtouchch/15474250"
    assert job.employment_type == "Full-time"
    assert job.description == (
        "Eine Stimme, die Türen öffnet.\n"
        "Dann lies weiter.\n\n"
        "Deine Aufgaben:\n"
        "- Schweizer KMU anrufen\n"
        "- Termine im CRM erfassen"
    )
    assert job.posted_at is None
    assert job.raw["id"] == SLUGS[0]
    assert job.raw["detail"]["cms_slug"] == SLUGS[0]


def test_webtouch_preserves_search_index_record_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if str(request.url) == INDEX_URL:
            return httpx.Response(200, json=search_index(1), request=request)
        return httpx.Response(503, request=request)

    job = (
        WebtouchJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == TITLES[0]
    assert job.url == f"{BASE_URL}/{SLUGS[0]}"
    assert job.apply_url == job.url
    assert job.location is None
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "must be an object"),
        ({"/karriere": {}}, "unexpected identity"),
        (
            {
                **search_index(1),
                f"/karriere/{SLUGS[0]}": {"h1": []},
            },
            "incomplete vacancy",
        ),
    ],
)
def test_webtouch_rejects_invalid_search_index(payload: object, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=message):
        WebtouchJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_webtouch_max_jobs_prevents_silent_catalog_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(200, json=search_index(), request=request)

    with pytest.raises(DirectCompanyRequestError, match="limit of 1 vacancies"):
        WebtouchJobsParser(
            max_jobs=1,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())


def test_webtouch_wraps_request_failures() -> None:
    parser = WebtouchJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_webtouch_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["webtouch"]
    assert isinstance(parser, WebtouchJobsParser)
    assert parser.base_url == settings.webtouch_jobs_base_url
    assert parser.max_jobs == settings.webtouch_jobs_max_jobs
    assert parser.detail_workers == settings.webtouch_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Webtouch", "filters": {}},
            "sources": ["webtouch", "webtouch"],
        }
    )
    assert request.sources == ["webtouch"]


def test_webtouch_jobs_render_as_direct_company_imports() -> None:
    parsed = (
        WebtouchJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(
                lambda request: (
                    httpx.Response(200, text=careers_html(), request=request)
                    if str(request.url) == BASE_URL
                    else httpx.Response(200, json=search_index(1), request=request)
                    if str(request.url) == INDEX_URL
                    else httpx.Response(200, text=detail_html(0), request=request)
                )
            ),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    stored = parsed_job_to_stored_job(
        parsed,
        job_id=f"webtouch-{SLUGS[0]}",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == f"webtouch-{SLUGS[0]}"
    assert stored["logo"] == "company"
    assert stored["department"] == "Webtouch GmbH import"
    assert stored["company"] == "Webtouch GmbH"
