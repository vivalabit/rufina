from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.akros import AkrosJobsParser, parse_detail_html
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.akros.test/jobs/"


def page_head(page_url: str, *, site_name: str = "AKROS") -> str:
    return f"""
    <head>
      <meta property="og:site_name" content="{site_name}">
      <link rel="canonical" href="{page_url}">
    </head>
    """


def listing_row(
    *,
    title: str,
    role_slug: str,
    locations: tuple[str, ...],
    duplicate_mobile_links: bool = True,
) -> str:
    abbreviations = {"biel": "BI", "zurich": "ZH", "luzern": "LU", "bern": "BE"}
    mobile_links = "/".join(
        f'<a href="{BASE_URL}{role_slug}/{location}/">{abbreviations[location]}</a>'
        for location in locations
    )
    desktop_cells = "".join(
        (
            f'<td><a href="{BASE_URL}{role_slug}/{location}/">{abbreviations[location]}</a></td>'
            if location in locations
            else "<td>&nbsp;</td>"
        )
        for location in ("biel", "zurich", "luzern", "bern")
    )
    mobile = f'<span class="mobLocals"> ({mobile_links})</span>' if duplicate_mobile_links else ""
    return f"<tr><td>{title}{mobile}</td>{desktop_cells}</tr>"


def listing_html(
    rows: list[str],
    *,
    site_name: str = "AKROS",
    category: str = "Entwicklung",
) -> str:
    return f"""
    <html lang="de">
      {page_head(BASE_URL, site_name=site_name)}
      <body><div id="jobsall"><table>
        <tr><th>&nbsp;</th><th>Biel (BI)</th><th>Zürich (ZH)</th>
          <th>Luzern (LU)</th><th>Bern (BE)</th></tr>
        <tr class="subHeadTableRow"><td class="jobsTableSubtitle">{category}</td>
          <td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
        {"".join(rows)}
      </table></div></body>
    </html>
    """


def detail_html(
    *,
    title: str,
    role_slug: str,
    location_slug: str,
    posting_id: str,
    canonical_url: str | None = None,
    form_action: str | None = None,
    profile_headings: tuple[str, ...] = ("Deine Skills", "Dein Profil"),
) -> str:
    detail_url = canonical_url or f"{BASE_URL}{role_slug}/{location_slug}/"
    profile_sections = "".join(
        f"<h3>{heading}</h3><ul><li>Mehrjährige Erfahrung im Software Engineering.</li></ul>"
        for heading in profile_headings
    )
    return f"""
    <html lang="de">
      {page_head(detail_url)}
      <head><title>{title} | AKROS</title></head>
      <body><div class="pageWrapper">
        <div class="jobintro"><p>AKROS entwickelt individuelle IT-Lösungen.</p></div>
        <div class="jobHeroInner">
          <h3>Deine Aufgaben</h3>
          <ul><li>Entwickle zuverlässige Software.</li><li>Berate unsere Kunden.</li></ul>
          {profile_sections}
          <h3>Unser Versprechen</h3>
          <p>Wir unterstützen deine fachliche und persönliche Entwicklung.</p>
          <h3>Kontakt</h3>
          <p>Samuel Zimmermann</p>
          <span class="applyBtn" id="applyforjob">Jetzt bewerben!</span>
          <a href="//www.akros.test/jobs/pdf/{posting_id}/{location_slug}">
            <span class="pdfBtn">PDF laden</span>
          </a>
          <form id="job-form" action="{form_action or detail_url}" method="post"></form>
        </div>
      </div></body>
    </html>
    """


def catalog_fixture() -> list[str]:
    return [
        listing_row(
            title="Java Software Engineer Fullstack",
            role_slug="java-software-engineer-fullstack",
            locations=("zurich", "bern"),
        ),
        listing_row(
            title="Scrum Master 60 – 100%",
            role_slug="scrum-master",
            locations=("biel",),
        ),
    ]


def test_akros_collects_complete_location_catalog_and_enriches_jobs() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/jobs/":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        role_slug, location_slug = request.url.path.strip("/").split("/")[1:]
        title = (
            "Scrum Master 60 – 100%"
            if role_slug == "scrum-master"
            else "Java Software Engineer Fullstack"
        )
        return httpx.Response(
            200,
            text=detail_html(
                title=title,
                role_slug=role_slug,
                location_slug=location_slug,
                posting_id="3495" if role_slug == "scrum-master" else "1446",
            ),
            request=request,
        )

    result = AkrosJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "/jobs/",
        "/jobs/java-software-engineer-fullstack/zurich/",
        "/jobs/java-software-engineer-fullstack/bern/",
        "/jobs/scrum-master/biel/",
    ]
    assert result.status == "completed"
    assert result.message == ("Scanned 3 AKROS Switzerland vacancies from the official catalog")
    assert len(result.jobs) == 3

    first = result.jobs[0]
    assert first.source == "akros"
    assert first.title == "Java Software Engineer Fullstack"
    assert first.company == "AKROS AG"
    assert first.location == "Zürich, Switzerland"
    assert first.url == ("https://www.akros.test/jobs/java-software-engineer-fullstack/zurich/")
    assert first.apply_url == first.url
    assert first.posted_at is None
    assert first.employment_type is None
    assert first.description and "AKROS entwickelt individuelle IT-Lösungen" in first.description
    assert first.description and "- Entwickle zuverlässige Software" in first.description
    assert first.description and "Samuel Zimmermann" not in first.description
    assert first.raw["category"] == "Entwicklung"
    assert first.raw["detail"]["posting_id"] == "1446"
    assert result.jobs[1].location == "Bern, Switzerland"
    assert result.jobs[2].location == "Biel/Bienne, Switzerland"
    assert result.jobs[2].employment_type == "60–100%"


def test_akros_preserves_listing_when_detail_fails() -> None:
    row = listing_row(
        title="Java Software Engineer Fullstack",
        role_slug="java-software-engineer-fullstack",
        locations=("zurich",),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs/":
            return httpx.Response(200, text=listing_html([row]), request=request)
        return httpx.Response(503, request=request)

    job = (
        AkrosJobsParser(base_url=BASE_URL, transport=httpx.MockTransport(handler))
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == "Java Software Engineer Fullstack"
    assert job.location == "Zürich, Switzerland"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_akros_rejects_incomplete_or_inconsistent_catalog() -> None:
    missing_mobile = listing_row(
        title="Java Software Engineer Fullstack",
        role_slug="java-software-engineer-fullstack",
        locations=("zurich",),
        duplicate_mobile_links=False,
    )
    duplicate = listing_row(
        title="Java Software Engineer Fullstack",
        role_slug="java-software-engineer-fullstack",
        locations=("zurich",),
    )

    def parser_for(rows: list[str]) -> AkrosJobsParser:
        return AkrosJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text=listing_html(rows),
                    request=request,
                )
            ),
        )

    with pytest.raises(DirectCompanyRequestError, match="mobile and desktop"):
        parser_for([missing_mobile]).search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser_for([duplicate, duplicate]).search(LinkedInSearchRequest())


def test_akros_rejects_wrong_identity_or_detail_contract() -> None:
    wrong_identity = AkrosJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=listing_html(catalog_fixture(), site_name="Other AG"),
                request=request,
            )
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())

    detail_url = f"{BASE_URL}scrum-master/biel/"
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                title="Scrum Master 60 – 100%",
                role_slug="scrum-master",
                location_slug="biel",
                posting_id="3495",
                form_action="https://attacker.example/jobs/scrum-master/biel/",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="scrum-master-biel",
            expected_title="Scrum Master 60 – 100%",
            expected_location_slug="biel",
        )


@pytest.mark.parametrize("profile_heading", ["Deine Skills", "Dein Profil"])
def test_akros_accepts_both_live_description_variants(profile_heading: str) -> None:
    detail_url = f"{BASE_URL}scrum-master/biel/"

    detail = parse_detail_html(
        detail_html(
            title="Scrum Master 60 – 100%",
            role_slug="scrum-master",
            location_slug="biel",
            posting_id="3495",
            profile_headings=(profile_heading,),
        ),
        page_url=detail_url,
        expected_url=detail_url,
        expected_job_id="scrum-master-biel",
        expected_title="Scrum Master 60 – 100%",
        expected_location_slug="biel",
    )

    assert profile_heading in detail["description"]


def test_akros_wraps_listing_request_failures() -> None:
    parser = AkrosJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_akros_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["akros"]
    assert isinstance(parser, AkrosJobsParser)
    assert parser.base_url == settings.akros_jobs_base_url
    assert parser.detail_workers == settings.akros_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "AKROS", "filters": {}},
            "sources": ["akros", "akros"],
        }
    )
    assert request.sources == ["akros"]


def test_akros_jobs_render_as_direct_company_imports() -> None:
    job = AkrosJobsParser().normalize_job(
        {
            "id": "java-software-engineer-fullstack-zurich",
            "title": "Java Software Engineer Fullstack",
            "location": "Zürich, Switzerland",
            "url": ("https://www.akros.ch/jobs/java-software-engineer-fullstack/zurich/"),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="akros-java-software-engineer-fullstack-zurich",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "AKROS AG import"
    assert stored["id"] == "akros-java-software-engineer-fullstack-zurich"
