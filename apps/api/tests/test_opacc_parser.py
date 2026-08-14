from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.opacc import OpaccJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://jobs.opacc.test/"


def record(
    slug: str,
    title: str,
    *,
    category_id: int = 1,
    location: str = "Rothenburg, Schweiz",
) -> dict[str, object]:
    category, category_slug = {
        1: ("Kunden bedienen", "kunden-bedienen"),
        2: ("Fundament ausbauen", "fundament-ausbauen"),
    }[category_id]
    return {
        "id": f"{category_slug}-{slug}",
        "title": title,
        "location": location,
        "summary": f"Kurzbeschreibung für {title}",
        "url": f"{BASE_URL}{category_slug}/{slug}.html",
        "category_id": category_id,
        "category": category,
    }


def card(item: dict[str, object]) -> str:
    return f"""
    <li>
      <span class="jobs-title"><a href="{item["url"]}"
        title="{item["summary"]}">{item["title"]}</a></span>
      <span class="jobs-city"><a href="{item["url"]}">{item["location"]}</a></span>
    </li>
    """


def homepage(category_1: list[dict[str, object]], category_2: list[dict[str, object]]) -> str:
    website = {
        "@context": "http://schema.org",
        "@type": "WebSite",
        "name": "Opacc Jobs",
        "url": BASE_URL,
    }

    def category_html(category_id: int, name: str, items: list[dict[str, object]]) -> str:
        return f"""
        <div class="col jobs"><h3>{name}</h3>
          <ul class="job-list">{"".join(card(item) for item in items[:4])}</ul>
          <button class="latest_ad_load_more" id="load_more_{category_id}"
            data-catid="{category_id}" data-pg="1" data-total="{len(items)}">Mehr Jobs</button>
        </div>
        """

    return f"""
    <html lang="DE"><head>
      <title>Opacc Jobs | Opacc Jobs</title>
      <base data-url="{BASE_URL}" data-domain="jobs.opacc.ch">
      <meta name="generator" content="Hannibal CMS">
      <meta property="og:url" content="{BASE_URL}">
      <script type="application/ld+json">{json.dumps(website)}</script>
    </head><body>
      <header><div class="logo"><img src="https://jobs.opacc.ch/images/logo.png"></div></header>
      <div id="jobs"><div class="container">
        <div class="city-filter">
          <label>Alle</label><label>Rothenburg, Schweiz</label><label>Münchenstein, Schweiz</label>
        </div>
        <div class="row">
          {category_html(1, "Kunden bedienen", category_1)}
          {category_html(2, "Fundament ausbauen", category_2)}
          <div class="jobs"><h3>Job Botschafter</h3></div>
        </div>
      </div></div>
      <footer><div class="logo"><img src="https://jobs.opacc.ch/images/opacc-logo-large.svg"></div>
        Opacc | Wahligenpark 1 | CH-6023 Rothenburg | +41 41 349 51 00 | jobs@opacc.ch
      </footer>
    </body></html>
    """


def catalog_payload(
    items: list[dict[str, object]],
    *,
    category_id: int,
    total: int,
) -> dict[str, str]:
    return {
        "html": (
            "".join(card(item) for item in items) + f"<!-- {category_id}_adTotalNo:{total} -->"
        ),
        "status": "OK",
    }


def detail_html(
    item: dict[str, object],
    *,
    schema_id: int,
    posted_at: str = "2026-07-21T10:00:00+02:00",
    apply_url: str = (
        "https://my.jobalino.ch/job/d35e7c9eca1bf859548f89d0f21b815a/"
        "opacc-software-ag/teamleiterin-support#application"
    ),
) -> str:
    location = str(item["location"])
    street, region, postal_code = {
        "Rothenburg, Schweiz": ("Wahligenpark 1", "Rothenburg", "6023"),
        "Münchenstein, Schweiz": ("Tramstrasse 66", "Münchenstein", "4142"),
    }[location]
    path = str(item["url"]).removeprefix(BASE_URL)
    return f"""
    <html lang="DE"><head>
      <base data-domain="jobs.opacc.ch" data-request-uri="{path}">
      <meta property="og:url" content="{item["url"]}">
      <meta property="og:site_name" content="Opacc Jobs">
    </head><body>
      <div class="container step1">
        <a class="back-button">Startseite</a>
        <h1>{item["title"]}</h1><h2>{location}</h2>
        <p>Du möchtest Teil eines engagierten Teams sein?</p>
        <h3>Dein Alltag</h3><ul><li>Du entwickelst nachhaltige Lösungen.</li></ul>
        <div class="row links"><a class="dark button" href="{apply_url}">Jetzt bewerben</a></div>
      </div>
      <script type="application/ld+json">
      {{
        "@type":"JobPosting",
        "title":"{item["title"]}",
        "datePosted":"{posted_at}",
        "industry":"{item["category"]}",
        "employmentType":"FULL_TIME",
        "hiringOrganization":{{"name":"Opacc","sameAs":"https://www.jobs.opacc.ch/",
          "logo":"https://jobs.opacc.ch/images/logo-fav.png"}},
        "jobLocation":{{"address":{{"streetAddress":"{street}",
          "addressLocality":"{location}","addressRegion":"{region}",
          "postalCode":"{postal_code}"}}}},
        "description":"unescaped\ntext",
        "identifier":{{"name":"Opacc","value":"{schema_id}"}}
      // }}
      </script>
    </body></html>
    """


def catalog_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    category_1 = [record(f"job-{index}", f"ERP Job {index}") for index in range(1, 6)]
    category_2 = [
        record(
            "cloud-engineer",
            "Cloud Engineer (80-100%)",
            category_id=2,
            location="Münchenstein, Schweiz",
        )
    ]
    return category_1, category_2


def parser_with_catalog(
    *,
    detail_status: int = 200,
    mutate_payload: bool = False,
) -> OpaccJobsParser:
    category_1, category_2 = catalog_fixture()
    all_items = [*category_1, *category_2]

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        if query.get("ajax") == ["adInfinity"]:
            category_id = int(query["category_id"][0])
            page_number = int(query["pg"][0])
            items = category_1 if category_id == 1 else category_2
            page_items = items[(page_number - 1) * 4 : page_number * 4]
            payload = catalog_payload(
                page_items,
                category_id=category_id,
                total=len(items),
            )
            if mutate_payload and category_id == 1 and page_number == 2:
                payload["html"] = payload["html"].replace("_adTotalNo:5", "_adTotalNo:6")
            return httpx.Response(200, json=payload, request=request)
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=homepage(category_1, category_2),
                request=request,
            )
        item = next(item for item in all_items if url_path(item["url"]) == request.url.path)
        if detail_status != 200:
            return httpx.Response(detail_status, request=request)
        index = all_items.index(item)
        apply_url = (
            "https://my.jobalino.ch/de/jobpreview/3012?tabid=tab2"
            if index == 1
            else (
                "https://my.jobalino.ch/job/d35e7c9eca1bf859548f89d0f21b815a/"
                f"opacc-software-ag/{str(item['id']).split('-', maxsplit=2)[-1]}#application"
            )
        )
        return httpx.Response(
            200,
            text=detail_html(item, schema_id=100 + index, apply_url=apply_url),
            request=request,
        )

    return OpaccJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    )


def url_path(value: object) -> str:
    return "/" + str(value).removeprefix(BASE_URL)


def test_opacc_collects_all_pages_and_enriches_every_vacancy() -> None:
    result = parser_with_catalog().search(LinkedInSearchRequest(results_limit=1))
    assert result.status == "completed"
    assert result.message == (
        "Scanned 6 Opacc Switzerland vacancies from the complete 2-category catalog"
    )
    assert len(result.jobs) == 6

    first = result.jobs[0]
    assert first.source == "opacc"
    assert first.title == "ERP Job 1"
    assert first.company == "Opacc Software AG"
    assert first.location == "6023 Rothenburg, Switzerland"
    assert first.posted_at == "2026-07-21"
    assert first.employment_type == "Full-time"
    assert "Du entwickelst nachhaltige Lösungen." in (first.description or "")
    assert first.apply_url and first.apply_url.startswith("https://my.jobalino.ch/job/")
    assert result.jobs[1].apply_url == ("https://my.jobalino.ch/de/jobpreview/3012?tabid=tab2")
    assert result.jobs[-1].location == "4142 Münchenstein, Switzerland"
    assert result.jobs[-1].employment_type == "Full-time · 80–100%"


def test_opacc_preserves_catalog_when_details_fail() -> None:
    result = parser_with_catalog(detail_status=503).search(LinkedInSearchRequest())
    assert len(result.jobs) == 6
    assert all(job.apply_url == job.url for job in result.jobs)
    assert all(job.description is None for job in result.jobs)
    assert all("503 Service Unavailable" in job.raw["detail_error"] for job in result.jobs)


def test_opacc_rejects_inconsistent_pagination() -> None:
    with pytest.raises(DirectCompanyRequestError, match="pagination metadata"):
        parser_with_catalog(mutate_payload=True).search(LinkedInSearchRequest())


def test_opacc_rejects_wrong_homepage_identity_and_http_failures() -> None:
    parser = OpaccJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<html><title>Lookalike jobs</title></html>",
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    parser = OpaccJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_opacc_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["opacc"]
    assert isinstance(parser, OpaccJobsParser)
    assert parser.base_url == settings.opacc_jobs_base_url
    assert parser.detail_workers == settings.opacc_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Opacc", "filters": {}},
            "sources": ["opacc", "opacc"],
        }
    )
    assert request.sources == ["opacc"]

    job = normalize_job(
        {
            "id": "kunden-bedienen-teamleiterin-support",
            "title": "TeamleiterIn Support",
            "location": "Rothenburg, Schweiz",
            "url": "https://jobs.opacc.ch/kunden-bedienen/teamleiterin-support.html",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="opacc-kunden-bedienen-teamleiterin-support",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Opacc Software AG import"
    assert stored["id"] == "opacc-kunden-bedienen-teamleiterin-support"
