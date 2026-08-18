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
from app.services.parsers.companies.aity import AityJobsParser, normalize_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner


def vacancy_record(index: int) -> dict[str, str]:
    job_id = f"{index + 1:08x}-d82d-4393-9412-{index + 100:012x}"
    return {
        "id": job_id,
        "slug": f"platform-engineer-{index}",
        "title": f"Platform Engineer {index} (a)",
        "workload": "80-100%",
        "city": "Bern-LIEBEfeld",
        "posted_at": f"2026-08-{index + 10:02d}",
    }


def job_url(record: dict[str, str]) -> str:
    return f"https://jobs.aity.ch/offene-stellen/{record['slug']}/{record['id']}"


def corporate_html(
    *,
    title: str = "Finde deinen Traumjob bei aity",
    iframe_url: str = "https://jobs.aity.ch/",
) -> str:
    return f"""
    <html lang="de-CH"><head><title>{title}</title>
      <base href="https://aity.ch/">
      <meta property="og:title" content="{title}">
      <meta property="og:url" content="https://aity.ch/jobs">
    </head><body><main><h1>Finde deinen Traumjob</h1>
      <script src="https://jobs.aity.ch/careercenter/1005606/assets/js/iframe-resizer.parent.js"></script>
      <iframe id="careercenter-pms" src="{iframe_url}"></iframe>
      <script>iframeResize({{checkOrigin: ['https://jobs.aity.ch']}}, '#careercenter-pms')</script>
    </main><footer><address>aity AG Schwarzenburgstrasse 160 3097 Liebefeld Schweiz</address></footer>
    </body></html>
    """


def listing_html(
    records: list[dict[str, str]],
    *,
    newsletter_title: str = "Nichts verpassen",
    language: str = "de",
) -> str:
    cards = "".join(
        f"""
        <a class="jobItem" id="job-{index}" href="{job_url(record)}"
           aria-label="{html.escape(record["title"])}" rel="noopener noreferrer"
           target="_blank"><div class="jobItemContent"><h2>
           {html.escape(record["title"])}<br><span>{record["workload"]}</span>
           </h2></div></a>
        """
        for index, record in enumerate(records)
    )
    return f"""
    <html lang="{language}"><head><title>aity AG: Career Center</title>
      <meta http-equiv="content-language" content="de">
      <link rel="stylesheet" href="/careercenter/1005606/assets/css/aity-careercenter.css?v=1">
    </head><body><main><div class="jobWrapper" id="jobs">{cards}
      <a class="infoItem abo" href="jobabo?lang=de"><h2>{newsletter_title}</h2></a>
    </div></main></body></html>
    """


def detail_html(
    record: dict[str, str],
    *,
    apply_id: str | None = None,
    country: str = "Schweiz",
) -> str:
    description = (
        "Du entwickelst zuverlässige Plattformen für die Schweizer Finanzbranche, "
        "übernimmst Verantwortung von der Konzeption bis zum Betrieb und arbeitest "
        "eng mit unseren Produkt-, Infrastruktur- und Security-Teams zusammen."
    )
    qualifications = (
        "Du verfügst über fundierte Informatikkenntnisse, arbeitest selbstständig "
        "und bringst deine Erfahrung konstruktiv in ein agiles Team ein."
    )
    responsibilities = (
        "Du konzipierst robuste Services, automatisierst Abläufe und stellst den "
        "sicheren, stabilen Betrieb unserer geschäftskritischen Systeme sicher."
    )
    posting = {
        "@context": "http://schema.org",
        "@type": "JobPosting",
        "title": record["title"],
        "description": f"<p>{description}</p>",
        "qualifications": f"<p>{qualifications}</p>",
        "responsibilities": f"<p>{responsibilities}</p>",
        "datePosted": record["posted_at"],
        "validThrough": "2026-09-30",
        "employmentType": "FULL_TIME",
        "industry": "Informatik",
        "hiringOrganization": {"@type": "Organization", "name": "aity AG"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": country,
                "addressLocality": record["city"],
                "addressRegion": "Bern",
                "streetAddress": "Schwarzenburgstrasse 160",
                "postalCode": "3097",
            },
        },
    }
    application_id = apply_id or record["id"]
    apply_url = f"https://ohws.prospective.ch/public/v1/redirect/{application_id}/ats/"
    document_title = f"{record['title']} - aity AG"
    return f"""
    <html lang="de"><head><title>{html.escape(document_title)}</title>
      <meta property="og:title" content="{html.escape(document_title)}">
      <meta name="author" content="aity AG"><meta name="copyright" content="aity AG">
      <link rel="canonical" href="{job_url(record)}">
    </head><body><header><div class="stellenTitel"><h1>{html.escape(record["title"])}
      <br>{record["workload"]}</h1></div><div class="subTitle"><h3>{record["city"]} | Homeoffice</h3></div>
    </header><main><a class="applyButton" href="{apply_url}">Bewerben</a>
      <a class="applyButton" href="{apply_url}">Jetzt bewerben</a></main></body></html>
    <script type="application/ld+json">{json.dumps(posting)}</script>
    """


def test_aity_collects_complete_catalog_and_enriches_details() -> None:
    records = [vacancy_record(0), vacancy_record(1)]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "aity.ch":
            return httpx.Response(200, text=corporate_html())
        if request.url.path == "/":
            return httpx.Response(200, text=listing_html(records))
        record = next(item for item in records if request.url.path == httpx.URL(job_url(item)).path)
        return httpx.Response(200, text=detail_html(record))

    result = AityJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert len(calls) == 4
    assert result.message == (
        "Scanned 2 aity vacancies from the complete official Career Center catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "aity"
    assert first.title == records[0]["title"]
    assert first.company == "aity AG"
    assert first.location == "Bern-Liebefeld, Switzerland"
    assert first.url == job_url(records[0])
    assert first.apply_url.endswith(f"/{records[0]['id']}/ats/")
    assert first.posted_at == "2026-08-10"
    assert first.employment_type == "80–100%"
    assert first.seniority is None
    assert first.description and first.description.startswith("Du entwickelst zuverlässige")
    assert first.raw["detail"]["valid_through"] == "2026-09-30"
    assert first.raw["detail"]["schema_employment_type"] == "FULL_TIME"


def test_aity_preserves_verified_listing_when_detail_fails() -> None:
    record = vacancy_record(0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "aity.ch":
            return httpx.Response(200, text=corporate_html())
        if request.url.path == "/":
            return httpx.Response(200, text=listing_html([record]))
        return httpx.Response(503, text="unavailable")

    job = (
        AityJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == record["title"]
    assert job.location == "Liebefeld, Switzerland"
    assert job.apply_url == job_url(record)
    assert job.employment_type == "80–100%"
    assert job.description is None
    assert "503" in str(job.raw["detail_error"])


@pytest.mark.parametrize(
    ("parent", "message"),
    [
        (corporate_html(title="Generic careers"), "unexpected identity"),
        (corporate_html(iframe_url="https://example.com/jobs"), "official Career Center"),
    ],
)
def test_aity_rejects_untrusted_parent_page(parent: str, message: str) -> None:
    parser = AityJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=parent))
    )
    with pytest.raises(DirectCompanyRequestError, match=message):
        parser.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        (listing_html([], language="en"), "unexpected identity"),
        (listing_html([], newsletter_title="Subscribe"), "newsletter marker"),
    ],
)
def test_aity_rejects_untrusted_career_center(catalog: str, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=corporate_html() if request.url.host == "aity.ch" else catalog,
        )

    with pytest.raises(DirectCompanyRequestError, match=message):
        AityJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())


def test_aity_rejects_duplicate_and_oversized_catalogs() -> None:
    record = vacancy_record(0)

    def parser_for(catalog: str, *, max_jobs: int = 100) -> AityJobsParser:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=corporate_html() if request.url.host == "aity.ch" else catalog,
            )

        return AityJobsParser(max_jobs=max_jobs, transport=httpx.MockTransport(handler))

    duplicate_catalog = listing_html([record, record])
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        parser_for(duplicate_catalog).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        parser_for(listing_html([record, vacancy_record(1)]), max_jobs=1).search(
            LinkedInSearchRequest()
        )


def test_aity_keeps_listing_when_detail_is_invalid() -> None:
    record = vacancy_record(0)
    wrong_id = vacancy_record(2)["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "aity.ch":
            return httpx.Response(200, text=corporate_html())
        if request.url.path == "/":
            return httpx.Response(200, text=listing_html([record]))
        return httpx.Response(200, text=detail_html(record, apply_id=wrong_id))

    job = (
        AityJobsParser(transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )
    assert job.title == record["title"]
    assert "application link" in str(job.raw["detail_error"])


def test_aity_accepts_explicit_empty_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=corporate_html() if request.url.host == "aity.ch" else listing_html([]),
        )

    result = AityJobsParser(transport=httpx.MockTransport(handler)).search(LinkedInSearchRequest())
    assert result.jobs == []
    assert result.message.startswith("Scanned 0 aity vacancies")


def test_aity_wraps_request_failures() -> None:
    parser = AityJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="temporarily unavailable"))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_aity_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["aity"]

    assert isinstance(parser, AityJobsParser)
    assert parser.base_url == settings.aity_jobs_base_url
    assert parser.career_center_url == settings.aity_jobs_career_center_url
    assert parser.max_jobs == settings.aity_jobs_max_jobs
    assert parser.detail_workers == settings.aity_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "aity AG", "filters": {}},
            "sources": ["aity", "aity"],
        }
    )
    assert request.sources == ["aity"]

    record = vacancy_record(0)
    stored = parsed_job_to_stored_job(
        normalize_job(
            {
                "id": record["id"],
                "title": record["title"],
                "location": "Liebefeld, Switzerland",
                "employment_type": "80–100%",
                "url": job_url(record),
            }
        ),
        job_id=f"aity-{record['id']}",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "aity AG import"
    assert stored["company"] == "aity AG"
