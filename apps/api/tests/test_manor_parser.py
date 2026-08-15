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
from app.services.parsers.companies.manor import ManorJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://careers.manor.ch/de/offene-stellen/offene-stellen"
FEED_URL = "https://live.solique.ch/manor/de/jobs/"
DETAIL_IDS = ("4041835", "4055106", "4055073")
REQUISITION_IDS = ("8044", "8184", "8177")
TITLES = (
    "Polydesigner*in 3D 80%",
    "Collaborateur/trice vente Mode – Maison & Beauté 60% (m/f/d)",
    "Mitarbeiter*in Visual Merchandising 60% (m/w/d)",
)


def careers_html() -> str:
    return f"""
    <html lang="de"><head>
      <title>Offene Stellen | Manor Jobs</title>
      <link rel="canonical" href="{BASE_URL}">
    </head><body>
      <iframe id="responsive-iframe" src="https://live.solique.ch/manor/de/"></iframe>
    </body></html>
    """


def listing_payload(indexes: list[int], *, page: int, total: int = 3) -> dict[str, object]:
    articles = "".join(
        f"""
        <article><div class="job-row-wrapper">
          <span class="job-row-1">{14 - index:02d}.08.2026<i> | </i> ID: {REQUISITION_IDS[index]}</span><br>
          <span class="job-row-2"><a href="/manor/job/details/{DETAIL_IDS[index]}/">{TITLES[index]}</a></span><br>
          <span class="job-row-3">{"Hinwil" if index == 0 else "Morges"}<i> | </i>{"Teilzeit 80%" if index == 0 else "Temps partiel 60%"}<i> | </i>unbefristet<i> | </i>sofort<i> | </i></span>
        </div></article>
        """
        for index in indexes
    )
    return {
        "html": f"""
          <section class="job-list"><div>{articles}</div></section>
          <section class="job-pagination"><a class="active current" data-page="{page}">{page}</a></section>
        """,
        "jobsCount": total,
        "filter": {},
        "lblNoResults": "Keine Resultate gefunden",
    }


def detail_html(index: int) -> str:
    detail_url = f"https://live.solique.ch/manor/job/details/{DETAIL_IDS[index]}/"
    location = "Hinwil" if index == 0 else "Morges"
    employment_type = "PART_TIME"
    posting = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": TITLES[index].replace("–", "\x96").replace("&", "&amp;"),
        "description": (
            f"{location}<br><br>{TITLES[index]}<br><br>"
            "Deine Verantwortung<br>- Kunden beraten<br>- Waren präsentieren"
        ),
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Manor AG",
            "sameAs": "https://www.manor.ch/",
        },
        "datePosted": f"2026-08-{14 - index:02d}T18:01:34+02:00",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
                "addressCountry": "CH",
            },
        },
        "employmentType": [employment_type],
    }
    apply_url = (
        "https://career55.sapsf.eu/careers?career_ns=job_application"
        f"&company=manorag&career_job_req_id={REQUISITION_IDS[index]}"
        "&jobPipeline=Manor%20Internet%202016"
    )
    return f"""
    <html><head><link rel="canonical" href="{detail_url}"></head><body>
      <div class="ad-apply"><a class="button" title="POSTULER" href="{apply_url.replace("&", "&amp;")}">POSTULER</a></div>
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </body></html>
    """


def test_manor_collects_every_page_and_enriches_json_ld_details() -> None:
    requests: list[tuple[str, str | int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            requests.append(("careers", BASE_URL))
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.path == "/manor/de/jobs/":
            page = int(request.url.params["page"])
            requests.append(("listing", page))
            indexes = [0, 1] if page == 1 else [2]
            return httpx.Response(
                200,
                json=listing_payload(indexes, page=page),
                request=request,
            )
        detail_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        index = DETAIL_IDS.index(detail_id)
        requests.append(("detail", index))
        return httpx.Response(200, text=detail_html(index), request=request)

    result = ManorJobsParser(
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert requests == [
        ("careers", BASE_URL),
        ("listing", 1),
        ("listing", 2),
        ("detail", 0),
        ("detail", 1),
        ("detail", 2),
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 3 Manor vacancies from 3 catalog records across 2 Solique pages"
    )
    assert len(result.jobs) == 3
    assert all(job.description for job in result.jobs)

    job = result.jobs[0]
    assert job.source == "manor"
    assert job.title == TITLES[0]
    assert job.company == "Manor AG"
    assert job.location == "Hinwil"
    assert job.url == f"https://live.solique.ch/manor/job/details/{DETAIL_IDS[0]}/"
    assert job.apply_url == (
        "https://career55.sapsf.eu/careers?career_ns=job_application"
        "&company=manorag&career_job_req_id=8044"
    )
    assert job.posted_at == "2026-08-14T18:01:34+02:00"
    assert job.employment_type == "Part-time"
    assert job.description == (
        "Hinwil\n\nPolydesigner*in 3D 80%\n\n"
        "Deine Verantwortung\n- Kunden beraten\n- Waren präsentieren"
    )
    assert job.raw["listing_page"] == 1
    assert job.raw["listing_pass"] == 1
    assert job.raw["total_available"] == 3
    assert job.raw["detail"]["structured_data"]["@type"] == "JobPosting"


def test_manor_preserves_listing_when_detail_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        if request.url.path == "/manor/de/jobs/":
            return httpx.Response(
                200,
                json=listing_payload([0], page=1, total=1),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = (
        ManorJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == TITLES[0]
    assert job.location == "Hinwil"
    assert job.posted_at == "2026-08-14"
    assert job.employment_type == "Part-time · Teilzeit 80%"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "must be an object"),
        ({"jobsCount": -1, "html": ""}, "invalid vacancy total"),
        ({"jobsCount": 1, "html": "<section></section>"}, "unexpected page"),
        (
            {
                **listing_payload([0], page=1, total=1),
                "html": listing_payload([0], page=2, total=1)["html"],
            },
            "unexpected page",
        ),
    ],
)
def test_manor_rejects_invalid_catalog(payload: object, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(200, json=payload, request=request)

    with pytest.raises(DirectCompanyRequestError, match=message):
        ManorJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_manor_max_pages_prevents_silent_catalog_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        return httpx.Response(
            200,
            json=listing_payload([0, 1], page=1),
            request=request,
        )

    with pytest.raises(DirectCompanyRequestError, match="limit of 1 pages"):
        ManorJobsParser(
            max_pages=1,
            transport=httpx.MockTransport(handler),
        ).search(LinkedInSearchRequest())


def test_manor_rejects_total_change_during_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BASE_URL:
            return httpx.Response(200, text=careers_html(), request=request)
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=listing_payload(
                [0, 1] if page == 1 else [2],
                page=page,
                total=3 if page == 1 else 4,
            ),
            request=request,
        )

    with pytest.raises(DirectCompanyRequestError, match="changed its vacancy total"):
        ManorJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_manor_wraps_request_failures() -> None:
    parser = ManorJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_manor_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["manor"]
    assert isinstance(parser, ManorJobsParser)
    assert parser.base_url == settings.manor_jobs_base_url
    assert parser.feed_url == settings.manor_jobs_feed_url
    assert parser.max_pages == settings.manor_jobs_max_pages
    assert parser.max_catalog_passes == settings.manor_jobs_max_catalog_passes
    assert parser.detail_workers == settings.manor_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Manor", "filters": {}},
            "sources": ["manor", "manor"],
        }
    )
    assert request.sources == ["manor"]


def test_manor_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": DETAIL_IDS[0],
        "title": TITLES[0],
        "location": "Hinwil",
        "posted_at": "2026-08-14",
        "employment_label": "Teilzeit 80%",
        "url": f"https://live.solique.ch/manor/job/details/{DETAIL_IDS[0]}/",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id=f"manor-{DETAIL_IDS[0]}",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["id"] == f"manor-{DETAIL_IDS[0]}"
    assert stored["logo"] == "company"
    assert stored["department"] == "Manor AG import"
    assert stored["company"] == "Manor AG"
