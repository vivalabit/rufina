from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.bedag import BedagJobsParser
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.bedag.test/de/jobs-und-karriere/offene-stellen/"


def listing_card(
    job_id: str,
    *,
    title: str,
    workload: str = "80– 100%",
    data_path: str | None = None,
    link_path: str | None = None,
) -> str:
    path = data_path or f"/de/aktuelles/offene-stellen/job_{job_id}.php"
    href = link_path or path
    return f"""
    <li class="listEntry clickable listEntryObject-job" data-url="{path}">
      <div class="listEntryInner">
        <div class="listEntryTitle">{title}</div>
        <div class="listEntryPensum"><div>{workload}</div></div>
        <a href="{href}">Zum Eintrag</a>
      </div>
    </li>
    """


def listing_html(cards: list[str]) -> str:
    return f"<html><body><main><ul>{''.join(cards)}</ul></main></body></html>"


def detail_html(
    job_id: str,
    *,
    title: str,
    workload: str = "80– 100%",
    location: str = "Bern, Engehaldenstrasse",
    alternate_job_id: str | None = None,
    apply_job_id: str | None = None,
) -> str:
    alternate_id = alternate_job_id or job_id
    application_id = apply_job_id or job_id
    return f"""
    <html class="object-job project-de"><head>
      <link rel="alternate" hreflang="de"
            href="https://www.bedag.test/de/aktuelles/offene-stellen/job_{alternate_id}.php">
      <meta property="og:title" content="{title}">
    </head><body><main><div id="blockContentInner">
      <section class="elementSection elementSection_var2">
        <div class="jobTitle"><h1>{title}<br>
          <span class="soft jobPercentage">{workload}</span>
        </h1></div>
        <div class="elementContainerStandardColumns_var36">
          <div class="col col1">
            <div class="elementText_var10"><p>
              <span class="soft">Standort</span><br>{location}
            </p></div>
            <div class="elementText_var10"><p>
              <span class="soft">Sprachen</span><br>Deutsch
            </p></div>
            <div class="elementText_var10"><p>
              <span class="soft">Stellen ID</span><br>{job_id}
            </p></div>
          </div>
          <div class="col col2"><div>
            <div class="elementText elementText_var20">
              <p>Wir entwickeln clevere ICT, die den Menschen nützt.</p>
            </div>
            <div class="elementHeadline elementHeadlineLevel_varh2">
              <h2>Dein neuer Job</h2>
            </div>
            <div class="elementText elementText_var0">
              <ul><li>Build useful services</li><li>Improve processes</li></ul>
            </div>
            <div class="elementHeadline elementHeadlineLevel_varh2">
              <h2>Das bringst du mit</h2>
            </div>
            <div class="elementText elementText_var0">
              <ul><li>Engineering experience</li></ul>
            </div>
          </div></div>
        </div>
      </section>
      <section class="elementSection elementSection_var12">
        <a href="https://recruitingapp-2898.umantis.com/Vacancies/{application_id}/Application/CheckLogin/1?lang=ger">
          Jetzt bewerben
        </a>
      </section>
    </div></main></body></html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_card("1008", title="Senior ICT-Controller (a)"),
        listing_card("1024", title="Senior Data &amp; Solution Engineer (a)"),
    ]


def test_bedag_collects_complete_catalog_and_enriches_vacancies() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/de/jobs-und-karriere/offene-stellen/":
            return httpx.Response(200, text=listing_html(catalog_fixture()))
        job_id = request.url.path.removesuffix(".php").rsplit("_", maxsplit=1)[-1]
        title = (
            "Senior ICT-Controller (a)"
            if job_id == "1008"
            else "Senior Data &amp; Solution Engineer (a)"
        )
        return httpx.Response(200, text=detail_html(job_id, title=title))

    result = BedagJobsParser(
        base_url=BASE_URL,
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls[0] == "/de/jobs-und-karriere/offene-stellen/"
    assert set(calls[1:]) == {
        "/de/aktuelles/offene-stellen/job_1008.php",
        "/de/aktuelles/offene-stellen/job_1024.php",
    }
    assert result.status == "completed"
    assert result.message == ("Scanned 2 Bedag Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "bedag"
    assert first.title == "Senior ICT-Controller (a)"
    assert first.company == "Bedag Informatik AG"
    assert first.location == "Bern, Engehaldenstrasse, Switzerland"
    assert first.url == ("https://www.bedag.test/de/aktuelles/offene-stellen/job_1008.php")
    assert first.apply_url == (
        "https://recruitingapp-2898.umantis.com/Vacancies/1008/Application/CheckLogin/1?lang=ger"
    )
    assert first.employment_type == "80–100%"
    assert first.description and "Dein neuer Job" in first.description
    assert first.description and "- Build useful services" in first.description
    assert first.raw["detail"]["id"] == "1008"
    assert result.jobs[1].title == "Senior Data & Solution Engineer (a)"


def test_bedag_preserves_safe_listing_when_detail_fails_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/de/jobs-und-karriere/offene-stellen/":
            return httpx.Response(
                200,
                text=listing_html([listing_card("1008", title="Senior ICT-Controller (a)")]),
            )
        return httpx.Response(
            200,
            text=detail_html(
                "1008",
                title="Senior ICT-Controller (a)",
                apply_job_id="9999",
            ),
        )

    job = (
        BedagJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Senior ICT-Controller (a)"
    assert job.location == "Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "incomplete vacancy" in str(job.raw["detail_error"])


def test_bedag_rejects_duplicate_or_unsafe_catalog_records() -> None:
    duplicate = listing_card("1008", title="Senior ICT-Controller (a)")
    duplicate_parser = BedagJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([duplicate, duplicate]))
        ),
    )
    unsafe_parser = BedagJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "1008",
                            title="Senior ICT-Controller (a)",
                            data_path="https://evil.example/job_1008.php",
                        )
                    ]
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate_parser.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        unsafe_parser.search(LinkedInSearchRequest())


def test_bedag_rejects_empty_or_ambiguous_catalog() -> None:
    empty = BedagJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="<html/>")),
    )
    ambiguous = BedagJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=listing_html(
                    [
                        listing_card(
                            "1008",
                            title="Senior ICT-Controller (a)",
                            link_path="/de/aktuelles/offene-stellen/job_9999.php",
                        )
                    ]
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="missing its vacancy catalog"):
        empty.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="ambiguous vacancy link"):
        ambiguous.search(LinkedInSearchRequest())


def test_bedag_wraps_listing_request_failures() -> None:
    parser = BedagJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_bedag_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["bedag"]
    assert isinstance(parser, BedagJobsParser)
    assert parser.base_url == settings.bedag_jobs_base_url
    assert parser.detail_workers == settings.bedag_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "Bedag", "filters": {}},
            "sources": ["bedag", "bedag"],
        }
    )
    assert request.sources == ["bedag"]


def test_bedag_jobs_render_as_direct_company_imports() -> None:
    job = BedagJobsParser().normalize_job(
        {
            "id": "1008",
            "title": "Senior ICT-Controller (a)",
            "url": "https://www.bedag.ch/de/aktuelles/offene-stellen/job_1008.php",
            "workload": "80– 100%",
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="bedag-1008",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "Bedag import"
    assert stored["id"] == "bedag-1008"


def test_bedag_parses_pdf_listing_and_document_with_php_warning_prefix() -> None:
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    from app.services.parsers.companies.bedag import parse_listing_html, parse_pdf_vacancy

    path = "/wAssets/docs/CFO-LeiterIn-Services.pdf"
    listing = listing_html([listing_card("", title="CFO & Leiter Services", data_path=path)])
    record = parse_listing_html(listing, page_url=BASE_URL, expected_url=BASE_URL)[0]
    assert record["id"].startswith("pdf-")
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 50 700 Td (Bedag Informatik AG seeks a CFO and Leiter Services to lead finance, accounting and business operations in Switzerland.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    detail = parse_pdf_vacancy(
        b"Warning: non-numeric value\n" + output.getvalue(), record=record, page_url=record["url"]
    )
    assert "Bedag Informatik AG" in detail["description"]
    with pytest.raises(DirectCompanyRequestError):
        parse_pdf_vacancy(b"<html>error</html>", record=record, page_url=record["url"])
