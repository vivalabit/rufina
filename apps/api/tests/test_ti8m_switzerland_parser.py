from __future__ import annotations

import json

import httpx
import pytest

from app.models.parsers import LinkedInSearchRequest
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.ti8m_switzerland import Ti8mSwitzerlandJobsParser

JOB_ONE = "cc7debd9-6eea-40f0-9c48-6a8152ca5227"
JOB_TWO = "0ea64980-08c6-4a5c-9712-5167ba25e8ed"
JOB_FOREIGN = "b83624ca-672c-47de-8a6f-18c031883348"


def listing_card(job_id: str, title: str, location: str, field: str = "Engineering") -> str:
    slug = title.lower().replace(" ", "-").replace("&", "and")
    return f"""
    <div class="job">
      <div class="title"><a href="https://career.ti8m.com/offene-stellen/{slug}/{job_id}"
        title="{title}">{title}<span></span></a></div>
      <div class="location">{location}</div><div class="branch">{field}</div>
    </div>
    """


def listing_page(cards: list[str], *, limit: str = "200") -> str:
    return f"""
    <html><body><form id="careercenter-form">
      <input name="offset" value="0"><input name="limit" value="{limit}">
      <input name="lang" value="en">
    </form><div id="jobs">{''.join(cards)}</div></body></html>
    """


def detail_page(job_id: str, title: str, *, city: str = "Zürich", country: str = "Schweiz") -> str:
    schema = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": title,
        "hiringOrganization": {"@type": "Organization", "name": "ti&m AG"},
        "jobLocation": {
            "@type": "Place",
            "address": {"addressCountry": country, "addressLocality": city},
        },
        "employmentType": "PART_TIME",
        "datePosted": "2026-07-30",
        "description": "<h3>What awaits you</h3><ul><li>Build digital products</li></ul>",
    }
    return f"""
    <html><body><article class="job"><div class="meta">
      <div><label>Erfahrung</label><span>+5 Jahre</span></div>
      <div><label>Beschäftigungsgrad</label><span>Unbefristet</span></div>
      <div><label>Seniorität</label><span>Senior</span></div>
    </div></article>
    <a class="button apply-button" href="https://ohws.prospective.ch/public/v1/redirect/{job_id}/ats/">Apply</a>
    </body></html><script type="application/ld+json">{json.dumps(schema)}</script>
    """


def test_ti8m_filters_global_catalog_to_switzerland_and_enriches_details() -> None:
    details: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "career.ti8m.test" and request.url.path == "/":
            return httpx.Response(200, text=listing_page([
                listing_card(JOB_ONE, "Senior Business Analyst", "Zurich"),
                listing_card(JOB_TWO, "Head Security Engineering", "Bern", "Security"),
                listing_card(JOB_FOREIGN, "AI Platform Architect", "Frankfurt"),
            ]))
        if request.url.host == "career.ti8m.com":
            job_id = request.url.path.rstrip("/").split("/")[-1]
            details.append(job_id)
            title = "Senior Business Analyst" if job_id == JOB_ONE else "Head Security Engineering"
            city = "Zürich" if job_id == JOB_ONE else "Bern"
            return httpx.Response(200, text=detail_page(job_id, title, city=city))
        raise AssertionError(f"Unexpected request {request.url}")

    result = Ti8mSwitzerlandJobsParser(
        catalog_url="https://career.ti8m.test/?lang=en",
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert set(details) == {JOB_ONE, JOB_TWO}
    assert result.message == "Scanned 2 ti&m Switzerland vacancies from 3 global vacancies"
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "ti8m_switzerland"
    assert first.company == "ti&m AG"
    assert first.title == "Senior Business Analyst"
    assert first.location == "Zürich, Switzerland"
    assert first.apply_url == f"https://ohws.prospective.ch/public/v1/redirect/{JOB_ONE}/ats/"
    assert first.posted_at == "2026-07-30"
    assert first.employment_type == "Unbefristet, Part-time"
    assert first.seniority == "Senior"
    assert first.description == "What awaits you\n- Build digital products"
    assert first.raw["professional_field"] == "Engineering"
    assert first.raw["total_available"] == 3


def test_ti8m_preserves_listing_when_detail_fails() -> None:
    page = listing_page([listing_card(JOB_ONE, "Cloud Engineer", "Basel", "Cloud")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page) if request.url.path == "/" else httpx.Response(503)

    job = Ti8mSwitzerlandJobsParser(
        catalog_url="https://career.ti8m.test/?lang=en",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.location == "Basel, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (listing_page([listing_card(JOB_ONE, "Engineer", "Zurich")], limit="20"), "complete catalog contract"),
        (listing_page([listing_card(JOB_ONE, "Engineer", "London")]), "unknown location"),
        (listing_page([listing_card(JOB_ONE, "Engineer", "Zurich"), listing_card(JOB_ONE, "Engineer", "Bern")]), "duplicate vacancy IDs"),
    ],
)
def test_ti8m_rejects_incomplete_or_ambiguous_catalog(page: str, message: str) -> None:
    parser = Ti8mSwitzerlandJobsParser(
        catalog_url="https://career.ti8m.test/?lang=en",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page)),
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_ti8m_rejects_non_swiss_detail_but_keeps_safe_listing() -> None:
    page = listing_page([listing_card(JOB_ONE, "Senior Engineer", "Zurich")])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text=page)
        return httpx.Response(200, text=detail_page(JOB_ONE, "Senior Engineer", city="Frankfurt", country="Deutschland"))

    job = Ti8mSwitzerlandJobsParser(
        catalog_url="https://career.ti8m.test/?lang=en",
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]
    assert job.location == "Zürich, Switzerland"
    assert "does not describe a Swiss location" in str(job.raw["detail_error"])
