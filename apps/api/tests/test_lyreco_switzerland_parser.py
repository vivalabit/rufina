from __future__ import annotations

import json

import httpx
import pytest

from app.core.settings import Settings
from app.models.parsers import LinkedInSearchRequest
from app.services.parser_validation import validate_parser_result
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.lyreco_switzerland import (
    LYRECO_SWITZERLAND_JOBS_URL,
    SWISS_COUNTRY_ID,
    WORKDAY_ORIGIN,
    WORKDAY_SITE,
    LyrecoSwitzerlandJobsParser,
)
from app.services.vacancy_search import create_vacancy_search_runner


def posting(index: int, *, suffix: str = "", location: str = "Dietikon ZH") -> dict:
    return {
        "title": f"Engineer {index}",
        "externalPath": f"/job/Dietikon-ZH/Engineer-{index}_JR-{1000 + index}{suffix}",
        "locationsText": location,
        "timeType": "Full time",
        "bulletFields": ["Switzerland"],
    }


def listing(items: list[dict], *, total: int | None = None) -> dict:
    total = len(items) if total is None else total
    return {
        "total": total,
        "jobPostings": items,
        "facets": [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locationCountry",
                        "values": [
                            {"id": SWISS_COUNTRY_ID, "descriptor": "Switzerland", "count": total}
                        ],
                    }
                ],
            }
        ],
    }


def detail(item: dict) -> dict:
    job_id = item["externalPath"].split("_JR-")[1].split("-")[0]
    return {
        "jobPostingInfo": {
            "jobReqId": f"JR-{job_id}",
            "title": item["title"],
            "externalUrl": f"{WORKDAY_ORIGIN}/{WORKDAY_SITE}{item['externalPath']}",
            "jobPostingSiteId": WORKDAY_SITE,
            "country": {"id": SWISS_COUNTRY_ID, "descriptor": "Switzerland"},
            "jobRequisitionLocation": {"country": {"id": SWISS_COUNTRY_ID, "alpha2Code": "CH"}},
            "location": item["locationsText"],
            "startDate": "2026-10-29",
            "timeType": "Full time",
            "jobDescription": "<h2>Your role</h2><p>Build useful software.</p>",
        }
    }


@pytest.mark.parametrize("omit_later_metadata", [True, False])
def test_lyreco_scans_every_country_page_and_enriches_all_locations(omit_later_metadata):
    items = [
        posting(i, location="Field Based - Perly" if i == 0 else "Dietikon ZH") for i in range(23)
    ]
    items[-1] = posting(22, suffix="-1")
    offsets = []

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["appliedFacets"] == {"locationCountry": [SWISS_COUNTRY_ID]}
            assert payload["searchText"] == ""
            offset = payload["offset"]
            offsets.append(offset)
            page = listing(items[offset : offset + 20], total=23)
            if offset and omit_later_metadata:
                page.update(total=0, facets=[])
            return httpx.Response(200, json=page)
        item = next(item for item in items if request.url.path.endswith(item["externalPath"]))
        return httpx.Response(200, json=detail(item))

    result = LyrecoSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest(results_limit=1, keywords="ignored")
    )
    assert offsets == [0, 20]
    assert len(result.jobs) == 23
    assert result.jobs[0].location == "Field Based - Perly, Switzerland"
    assert result.jobs[-1].raw["id"] == "JR-1022"
    assert all(job.description and job.apply_url.endswith("/apply") for job in result.jobs)
    assert validate_parser_result(result)[1] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(total=True),
        lambda p: p["facets"].clear(),
        lambda p: p["jobPostings"][0].update(externalPath="https://attacker.test/job"),
        lambda p: p["jobPostings"][0].update(bulletFields=["Germany"]),
        lambda p: p["jobPostings"][0].update(title=""),
        lambda p: p.update(total=2),
    ],
)
def test_lyreco_rejects_unverified_or_incomplete_catalog(mutation):
    payload = listing([posting(0)])
    mutation(payload)
    with pytest.raises(DirectCompanyRequestError):
        LyrecoSwitzerlandJobsParser(
            transport=httpx.MockTransport(
                lambda _, payload=payload: httpx.Response(200, json=payload)
            )
        ).search(LinkedInSearchRequest())


def test_lyreco_rejects_duplicates_and_catalog_limits():
    for payload, kwargs in [
        (listing([posting(0), posting(0)]), {}),
        (listing([posting(0)], total=21), {"max_pages": 1}),
        (listing([posting(0)], total=2), {"max_jobs": 1}),
    ]:
        with pytest.raises(DirectCompanyRequestError):
            LyrecoSwitzerlandJobsParser(
                **kwargs,
                transport=httpx.MockTransport(
                    lambda _, payload=payload: httpx.Response(200, json=payload)
                ),
            ).search(LinkedInSearchRequest())


@pytest.mark.parametrize("change", ["identity", "country", "url", "description", "http"])
def test_lyreco_preserves_verified_listing_if_detail_fails(change, monkeypatch):
    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", lambda _: None)
    item = posting(1)
    payload = detail(item)
    if change == "identity":
        payload["jobPostingInfo"]["jobReqId"] = "JR-9999"
    if change == "country":
        payload["jobPostingInfo"]["country"]["id"] = "foreign"
    if change == "url":
        payload["jobPostingInfo"]["externalUrl"] = "https://attacker.test/job"
    if change == "description":
        payload["jobPostingInfo"]["jobDescription"] = ""

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json=listing([item]))
        return httpx.Response(503) if change == "http" else httpx.Response(200, json=payload)

    result = LyrecoSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
        LinkedInSearchRequest()
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].raw["detail_error"]
    assert validate_parser_result(result)[1]


def test_lyreco_rejects_total_change_between_pages():
    items = [posting(i) for i in range(21)]

    def handler(request):
        offset = json.loads(request.content)["offset"]
        return httpx.Response(
            200, json=listing(items[:20] if not offset else [], total=21 if not offset else 20)
        )

    with pytest.raises(DirectCompanyRequestError, match="changed"):
        LyrecoSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
            LinkedInSearchRequest()
        )


def test_lyreco_accepts_explicit_empty_country_catalog():
    result = LyrecoSwitzerlandJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=listing([])))
    ).search(LinkedInSearchRequest())
    assert result.jobs == []
    assert validate_parser_result(result)[1] is None


def test_lyreco_migrates_saved_drupal_url_and_remains_registered():
    parser = LyrecoSwitzerlandJobsParser(
        base_url="https://www.lyreco.com/group/switzerland/de/jobs?f[0]=job_location:dietikon%20zh"
    )
    assert parser.base_url == LYRECO_SWITZERLAND_JOBS_URL
    registered = create_vacancy_search_runner(Settings(_env_file=None)).parsers[
        "lyreco_switzerland"
    ]
    assert isinstance(registered, LyrecoSwitzerlandJobsParser)
    assert registered.base_url == LYRECO_SWITZERLAND_JOBS_URL
