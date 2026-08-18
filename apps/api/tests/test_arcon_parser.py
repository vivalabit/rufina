from __future__ import annotations

import html
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.arcon import (
    ARCON_TENANT_ID,
    ArconJobsParser,
    normalize_job,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy_record(index: int) -> dict[str, str]:
    return {
        "slug": f"platform-engineer-{index}",
        "base_title": f"Platform Engineer {index}",
        "title": f"Platform Engineer {index} 80-100 % (m/w/d)",
        "application_id": f"{index + 1:08x}-a120-79d4-e16d-{index + 100:012x}",
        "posted_at": f"2026-08-{index + 10:02d}",
    }


INITIATIVE_ID = "e7c11a05-7bf1-3446-d138-7d91515eee1a"


def job_url(record: dict[str, str]) -> str:
    return f"https://www.arcon.ch/{record['slug']}/"


def application_url(application_id: str) -> str:
    return (
        "https://app.jobportal.abaservices.ch/application-process/"
        f"{ARCON_TENANT_ID}/{application_id}"
    )


def rank_schema(*, url: str, title: str, published_at: str = "2026-08-01") -> str:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://www.arcon.ch/#organization",
                "name": "Arcon Informatik AG",
            },
            {
                "@type": "WebPage",
                "url": url,
                "name": title,
                "datePublished": f"{published_at}T10:00:00+00:00",
            },
            {
                "@type": "Article",
                "name": title,
                "datePublished": f"{published_at}T10:00:00+00:00",
            },
        ],
    }
    return json.dumps(payload)


def listing_html(
    records: list[dict[str, str]],
    *,
    title: str = "ICT und Abacus Jobs | Offene Stellen",
    include_initiative: bool = True,
    visible_list: bool = True,
) -> str:
    cards = "".join(
        f"""
        <li class="elementor-icon-list-item"><a href="{job_url(record)}" target="_blank">
          <span class="elementor-icon-list-text">{html.escape(record["title"])}</span>
        </a></li>
        """
        for record in records
    )
    if include_initiative:
        cards += f"""
        <li class="elementor-icon-list-item"><a href="{application_url(INITIATIVE_ID)}"
          target="_blank" rel="noopener"><span class="elementor-icon-list-text">
          Initiativbewerbung</span></a></li>
        """
    list_classes = "elementor-widget-icon-list"
    if not visible_list:
        list_classes += " elementor-hidden-desktop"
    canonical = "https://www.arcon.ch/ict-und-abacus-jobs/"
    return f"""
    <html lang="de"><head><title>{title}</title>
      <link rel="canonical" href="{canonical}">
      <meta property="og:title" content="{title}">
      <meta property="og:site_name" content="Arcon Informatik AG">
      <script type="application/ld+json" class="rank-math-schema">
        {rank_schema(url=canonical, title=title)}
      </script>
    </head><body><main><section id="OffeneStellen">
      <h2>Unsere offenen ICT und Abacus Jobs</h2>
      <div class="elementor-widget-icon-list elementor-hidden-desktop elementor-hidden-laptop
        elementor-hidden-tablet elementor-hidden-mobile"><ul></ul></div>
      <div class="{list_classes}"><ul>{cards}</ul></div>
      <h3>Keine passende Stelle gefunden? Dann schick uns deine Initiativbewerbung und
        zeig uns deine Skills!</h3>
    </section></main><footer>ARCON Informatik AG Hinterbergstrasse 24
      6312 Steinhausen</footer></body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    application_id: str | None = None,
    visible_title: str | None = None,
) -> str:
    document_title = f"{record['base_title']} | Offene Stellen | Arcon"
    bullets = "".join(
        f'<li><span class="elementor-icon-list-text">Aufgabe {index}: Du planst, '
        "realisierst und betreibst zuverlässige ICT-Lösungen für unsere Kunden mit "
        "hoher Eigenverantwortung und sorgfältiger Dokumentation.</span></li>"
        for index in range(8)
    )
    apply_id = application_id or record["application_id"]
    return f"""
    <html lang="de"><head><title>{html.escape(document_title)}</title>
      <link rel="canonical" href="{job_url(record)}">
      <meta property="og:title" content="{html.escape(document_title)}">
      <meta property="og:site_name" content="Arcon Informatik AG">
      <script class="rank-math-schema" type="application/ld+json">
        {rank_schema(url=job_url(record), title=document_title)}
      </script>
    </head><body class="page page-id-700"><div data-elementor-type="wp-page"
      data-elementor-post-type="page" data-elementor-id="700">
      <h1>{html.escape(visible_title or record["base_title"])}</h1>
      <p>{html.escape(record["title"])}</p>
      <a href="{application_url(apply_id)}?jp=ABACUS">Jetzt bewerben</a>
      <section id="neuerJob"><h2>Über die Stelle</h2>
        <p>Bei uns entwickelst du keine Standardlösungen, sondern nachhaltige
        ICT-Plattformen. Du übernimmst Verantwortung von der Konzeption bis zum Betrieb
        und arbeitest eng mit unseren Kundinnen, Kunden und dem gesamten Team zusammen.</p>
        <h3>Deine Aufgaben</h3><ul>{bullets}</ul>
        <h3>Was du mitbringst</h3><p>Fundierte Informatikausbildung, analytisches Denken,
        Teamgeist und Freude an anspruchsvollen technischen Herausforderungen.</p>
      </section>
    </div><footer>ARCON Informatik AG Hinterbergstrasse 24 6312 Steinhausen</footer>
    </body></html>
    """


def application_html(
    *,
    application_id: str,
    title: str,
    posted_at: str,
    country: str = "CH",
) -> str:
    posting = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "position": 2011,
        "publication": 1,
        "title": title,
        "description": "",
        "identifier": {
            "@type": "PropertyValue",
            "name": " Arcon Informatik AG",
            "value": application_id,
        },
        "datePosted": posted_at,
        "validThrough": "",
        "hiringOrganization": {
            "@type": "Organization",
            "name": " Arcon Informatik AG",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Hinterbergstrasse",
                "addressLocality": "Steinhausen",
                "addressRegion": "ZG",
                "postalCode": "6312",
                "addressCountry": country,
            },
        },
    }
    return f"""
    <html><head><title>Bewerbungsprozess - Portal</title>
      <meta property="page-type" content="application-process">
      <script type="application/ld+json">{json.dumps(posting)}</script>
    </head><body></body></html>
    """


def make_handler(
    records: list[dict[str, str]],
    *,
    fail_detail_slug: str | None = None,
    invalid_application_id: str | None = None,
) -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.rstrip("/") == "/ict-und-abacus-jobs":
            return httpx.Response(200, text=listing_html(records))
        if request.url.host == "www.arcon.ch":
            slug = request.url.path.strip("/")
            if slug == fail_detail_slug:
                return httpx.Response(503, text="unavailable")
            record = next(item for item in records if item["slug"] == slug)
            return httpx.Response(200, text=detail_html(record))
        application_id = request.url.path.rstrip("/").split("/")[-1]
        if application_id == INITIATIVE_ID:
            return httpx.Response(
                200,
                text=application_html(
                    application_id=INITIATIVE_ID,
                    title="Initiativbewerbung",
                    posted_at="2026-06-02",
                ),
            )
        record = next(item for item in records if item["application_id"] == application_id)
        return httpx.Response(
            200,
            text=application_html(
                application_id=application_id,
                title=record["base_title"],
                posted_at=record["posted_at"],
                country="DE" if application_id == invalid_application_id else "CH",
            ),
        )

    return httpx.MockTransport(handler), calls


def test_arcon_collects_visible_catalog_and_reconciles_applications() -> None:
    records = [vacancy_record(0), vacancy_record(1)]
    transport, calls = make_handler(records)

    result = ArconJobsParser(detail_workers=3, transport=transport).search(
        LinkedInSearchRequest(results_limit=1)
    )

    assert len(calls) == 6
    assert result.message == (
        "Scanned 3 Arcon vacancies from the complete visible official catalog"
    )
    assert len(result.jobs) == 3
    first = result.jobs[0]
    assert first.source == "arcon"
    assert first.title == "Platform Engineer 0 80–100% (m/w/d)"
    assert first.company == "Arcon Informatik AG"
    assert first.location == "Steinhausen, Switzerland"
    assert first.url == job_url(records[0])
    assert first.apply_url == application_url(records[0]["application_id"])
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "80–100%"
    assert first.description and "Deine Aufgaben" in first.description
    assert first.raw["detail"]["page_published_at"] == "2026-08-01"
    initiative = result.jobs[2]
    assert initiative.title == "Initiativbewerbung"
    assert initiative.posted_at == "2026-06-02"
    assert initiative.apply_url == application_url(INITIATIVE_ID)
    assert initiative.description and initiative.description.startswith("Keine passende Stelle")


def test_arcon_preserves_listing_when_detail_fails() -> None:
    record = vacancy_record(0)
    transport, _ = make_handler([record], fail_detail_slug=record["slug"])
    jobs = ArconJobsParser(transport=transport).search(LinkedInSearchRequest()).jobs

    regular = jobs[0]
    assert regular.title == "Platform Engineer 0 80–100% (m/w/d)"
    assert regular.apply_url == job_url(record)
    assert regular.description is None
    assert "503" in str(regular.raw["detail_error"])
    assert jobs[1].title == "Initiativbewerbung"


def test_arcon_preserves_description_when_application_metadata_is_invalid() -> None:
    record = vacancy_record(0)
    transport, _ = make_handler([record], invalid_application_id=record["application_id"])
    job = ArconJobsParser(transport=transport).search(LinkedInSearchRequest()).jobs[0]

    assert job.description and "Deine Aufgaben" in job.description
    assert job.apply_url == application_url(record["application_id"])
    assert job.posted_at is None
    assert "JobPosting data" in str(job.raw["application_error"])


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (listing_html([], title="Generic careers"), "unexpected identity"),
        (listing_html([], visible_list=False), "visible vacancy catalog"),
        (listing_html([], include_initiative=False), "initiative application count"),
    ],
)
def test_arcon_rejects_untrusted_catalogs(catalog: str, message: str) -> None:
    parser = ArconJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=catalog))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


def test_arcon_rejects_duplicate_and_oversized_catalogs() -> None:
    record = vacancy_record(0)
    duplicate = listing_html([record, record])
    oversized = listing_html([record, vacancy_record(1)])

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        ArconJobsParser(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=duplicate))
        ).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        ArconJobsParser(
            max_jobs=1,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=oversized)),
        ).search(LinkedInSearchRequest())


def test_arcon_keeps_listing_when_detail_page_is_invalid() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/") == "/ict-und-abacus-jobs":
            return httpx.Response(200, text=listing_html([record]))
        if request.url.host == "www.arcon.ch":
            return httpx.Response(
                200,
                text=detail_html(record, visible_title="Different vacancy"),
            )
        return httpx.Response(
            200,
            text=application_html(
                application_id=INITIATIVE_ID,
                title="Initiativbewerbung",
                posted_at="2026-06-02",
            ),
        )

    jobs = (
        ArconJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest()).jobs
    )
    assert jobs[0].description is None
    assert "visible vacancy" in str(jobs[0].raw["detail_error"])


def test_arcon_wraps_listing_request_failures() -> None:
    parser = ArconJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_arcon_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["arcon"]

    assert isinstance(parser, ArconJobsParser)
    assert parser.base_url == settings.arcon_jobs_base_url
    assert parser.max_jobs == settings.arcon_jobs_max_jobs
    assert parser.detail_workers == settings.arcon_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Arcon Informatik AG", "filters": {}},
            "sources": ["arcon", "arcon"],
        }
    )
    assert request.sources == ["arcon"]

    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["slug"],
                "title": record["title"],
                "location": "Steinhausen, Switzerland",
                "employment_type": "80–100%",
                "url": job_url(record),
            }
        ),
        job_id=f"arcon-{record['slug']}",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "Arcon Informatik AG import"
    assert stored["company"] == "Arcon Informatik AG"
