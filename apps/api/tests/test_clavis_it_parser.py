from __future__ import annotations

import html
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.clavis_it import (
    CLAVIS_IT_JOBS_URL,
    ClavisItJobsParser,
    canonical_smartrecruiters_apply_url,
    normalize_job,
    normalize_location,
    normalize_workload,
    parse_german_date,
)
from app.services.vacancy_search import create_vacancy_search_runner

REGULAR = {
    "slug": "platform-devops-engineer-kubernetes",
    "path": "/karriere/jobs/platform-devops-engineer-kubernetes",
    "title": "Platform DevOps Engineer Kubernetes (w/m/d)",
    "summary": (
        "Du gestaltest die Plattformen, auf denen moderne und zuverlässige "
        "Kundenlösungen betrieben werden."
    ),
    "location": "Herisau / Winterthur",
    "workload": "80 - 100%",
}
TRAINING = {
    "slug": "schnupperlehre",
    "path": "/schnupperlehre",
    "title": "Schnupperlehre als Informatiker EFZ Applikationsentwicklung",
    "summary": "Möchtest Du in den Beruf Informatiker reinschnuppern? Dann bist Du richtig.",
    "location": "Herisau",
    "workload": "2 Tage",
}
RECORDS = [REGULAR, TRAINING]
APPLICATION_UUID = "01328b0b-0ca8-4470-93bc-ff30d9be6940"


def listing_html(
    records: list[dict[str, str]] = RECORDS,
    *,
    page_title: str = "Jobs - clavis IT ag",
) -> str:
    cards = "".join(
        f"""
        <div class="job"><div class="job__content">
          <h2 class="job__title">{html.escape(record["title"])}</h2>
          <p class="job__description">{html.escape(record["summary"])}</p>
          <div class="job__meta">
            <p class="job__location">{record["location"]}</p>
            <p class="job__workload">{record["workload"]}</p>
          </div>
          <a href="{record["path"]}" class="job__action">Mehr erfahren</a>
        </div></div>
        """
        for record in records
    )
    return f"""
    <html lang="de-DE"><head>
      <title>{page_title}</title>
      <link rel="canonical" href="{CLAVIS_IT_JOBS_URL}">
      <meta property="og:title" content="{page_title}">
      <meta property="og:site_name" content="clavis IT ag">
    </head><body>
      <a class="header__logo"><img alt="clavis IT ag Logo"></a>
      <section id="content">
        <h1>Offene Stellen</h1>
        <div class="lfr-layout-structure-item-jobs"><div class="jobs">{cards}</div></div>
      </section>
    </body></html>
    """


def description_html(*, training: bool = False) -> str:
    if training:
        intro = (
            "<p><b>Einleitung</b> Du interessierst dich für Informatik und möchtest "
            "zwei spannende Tage bei uns verbringen und unser Team kennenlernen.</p>"
            "<p><b>Was dich erwartet</b></p>"
        )
        profile = "<p><b>Was du mitbringen solltest</b></p>"
    else:
        intro = (
            "<p>Unser Business-Delivery-Team entwickelt und betreibt zuverlässige "
            "digitale Kundenlösungen. Du gestaltest Plattformen, Automatisierung "
            "und Standards eigenverantwortlich gemeinsam mit dem Team.</p>"
            "<p><strong>Das ist deine Aufgabe:</strong></p>"
        )
        profile = "<p><strong>Was Du mitbringen solltest</strong></p>"
    tasks = "".join(
        f"<li>Verantwortungsvolle und abwechslungsreiche Aufgabe Nummer {index}</li>"
        for index in range(1, 7)
    )
    requirements = "".join(
        f"<li>Praxisnahe fachliche Voraussetzung und Teamkompetenz Nummer {index}</li>"
        for index in range(1, 7)
    )
    return f"{intro}<ul>{tasks}</ul>{profile}<ul>{requirements}</ul>"


def detail_html(
    record: dict[str, str],
    *,
    document_title: str | None = None,
    apply_host: str = "jobs.smartrecruiters.com",
) -> str:
    training = record["path"] == "/schnupperlehre"
    url = f"https://www.clavisit.com{record['path']}"
    title = document_title or (
        "Schnupperlehre - clavis IT ag" if training else f"{record['title']} - clavis IT ag"
    )
    if training:
        apply_url = "mailto:bewerbung@clavisit.com"
        metadata = ""
    else:
        apply_url = (
            f"https://{apply_host}/oneclick-ui/company/ClavisITAg/publication/"
            f"{APPLICATION_UUID}?dcr_ci=ClavisITAg"
        )
        metadata = """
          <p><strong>Veröffentlicht:</strong> 17. August 2026</p>
          <p><strong>Pensum:</strong> 80 - 100%</p>
          <p><strong>Vertrag:</strong> Festanstellung</p>
          <p><strong>Sprache:</strong> Deutsch (fliessend), Englisch</p>
          <p><strong>Arbeitsort:</strong> Herisau, Winterthur</p>
          <p><strong>Start:</strong> ab sofort, nach Vereinbarung</p>
        """
    return f"""
    <html lang="de-DE"><head>
      <title>{html.escape(title)}</title>
      <link rel="canonical" href="{url}">
      <meta property="og:title" content="{html.escape(title)}">
      <meta property="og:site_name" content="clavis IT ag">
      <meta property="og:url" content="{url}">
    </head><body><section id="content">
      <h1 class="component-heading">{html.escape(record["title"])}</h1>
      <div class="component-paragraph" data-lfr-editable-id="element-text">
        {description_html(training=training)}
      </div>
      {metadata}
      <a href="{apply_url}">Jetzt bewerben</a>
    </section></body></html>
    """


def test_clavis_it_collects_regular_and_training_vacancies_with_details() -> None:
    detail_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/jobs":
            return httpx.Response(200, text=listing_html())
        detail_requests.append(request.url.path)
        record = next(item for item in RECORDS if item["path"] == request.url.path)
        return httpx.Response(200, text=detail_html(record))

    result = ClavisItJobsParser(
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert set(detail_requests) == {REGULAR["path"], TRAINING["path"]}
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 Clavis IT vacancies from the complete visible official careers catalog"
    )
    assert len(result.jobs) == 2
    regular, training = result.jobs
    assert regular.source == "clavis_it"
    assert regular.title == REGULAR["title"]
    assert regular.company == "clavis IT ag"
    assert regular.location == "Herisau / Winterthur, Switzerland"
    assert regular.url == f"https://www.clavisit.com{REGULAR['path']}"
    assert regular.apply_url and APPLICATION_UUID in regular.apply_url
    assert regular.posted_at == "2026-08-17"
    assert regular.employment_type == "80–100%"
    assert regular.description and "Das ist deine Aufgabe" in regular.description
    assert regular.description.count("- ") == 12
    assert regular.raw["detail"]["application_id"] == APPLICATION_UUID

    assert training.title == TRAINING["title"]
    assert training.location == "Herisau, Switzerland"
    assert training.employment_type == "2 Tage"
    assert training.posted_at is None
    assert training.apply_url == "mailto:bewerbung@clavisit.com"
    assert training.description and "Was dich erwartet" in training.description


def test_clavis_it_preserves_listing_data_when_detail_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/karriere/jobs":
            return httpx.Response(200, text=listing_html([REGULAR]))
        return httpx.Response(503, text="unavailable")

    job = (
        ClavisItJobsParser(
            detail_workers=1,
            transport=httpx.MockTransport(handler),
        )
        .search(LinkedInSearchRequest())
        .jobs[0]
    )

    assert job.title == REGULAR["title"]
    assert job.location == "Herisau / Winterthur, Switzerland"
    assert job.apply_url == job.url
    assert job.description == REGULAR["summary"]
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_clavis_it_rejects_listing_identity_duplicates_and_catalog_limit() -> None:
    wrong_identity = ClavisItJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html(page_title="Lookalike jobs"))
        )
    )
    duplicate = ClavisItJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=listing_html([REGULAR, REGULAR]))
        )
    )
    oversized = ClavisItJobsParser(
        max_jobs=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=listing_html())),
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancies"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_clavis_it_rejects_mismatched_detail_and_unsafe_application() -> None:
    scenarios = [
        detail_html(REGULAR, document_title="Different role - clavis IT ag"),
        detail_html(REGULAR, apply_host="evil.example"),
    ]

    for detail in scenarios:

        def handler(request: httpx.Request, value: str = detail) -> httpx.Response:
            if request.url.path == "/karriere/jobs":
                return httpx.Response(200, text=listing_html([REGULAR]))
            return httpx.Response(200, text=value)

        job = (
            ClavisItJobsParser(transport=httpx.MockTransport(handler))
            .search(LinkedInSearchRequest())
            .jobs[0]
        )
        assert "detail_error" in job.raw
        assert job.apply_url == job.url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("80 - 100%", "80–100%"),
        ("80–100 %", "80–100%"),
        ("2 Tage", "2 Tage"),
        ("100–80%", None),
    ],
)
def test_normalize_workload(value: str, expected: str | None) -> None:
    assert normalize_workload(value) == expected


def test_clavis_it_normalizes_only_known_swiss_locations_and_dates() -> None:
    assert normalize_location("Herisau / Winterthur / remote") == (
        "Herisau / Winterthur / Remote, Switzerland"
    )
    assert normalize_location("Berlin") is None
    assert parse_german_date("3. Juli 2026") == "2026-07-03"
    assert parse_german_date("July 3, 2026") is None


def test_clavis_it_accepts_only_official_smartrecruiters_applications() -> None:
    valid = (
        "https://jobs.smartrecruiters.com/oneclick-ui/company/ClavisITAg/publication/"
        f"{APPLICATION_UUID}?dcr_ci=ClavisITAg"
    )
    assert canonical_smartrecruiters_apply_url(valid) == valid
    assert canonical_smartrecruiters_apply_url(valid.replace("ClavisITAg", "Lookalike", 1)) is None
    assert (
        canonical_smartrecruiters_apply_url(valid.replace("dcr_ci=ClavisITAg", "dcr_ci=Other"))
        is None
    )


def test_clavis_it_wraps_listing_request_failures() -> None:
    parser = ClavisItJobsParser(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, text="unavailable"))
    )

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_clavis_it_is_registered_and_renders_as_direct_company() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["clavis_it"]

    assert isinstance(parser, ClavisItJobsParser)
    assert parser.base_url == settings.clavis_it_jobs_base_url
    assert parser.max_jobs == settings.clavis_it_jobs_max_jobs
    assert parser.detail_workers == settings.clavis_it_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "clavis IT ag", "filters": {}},
            "sources": ["clavis_it", "clavis_it"],
        }
    )
    assert request.sources == ["clavis_it"]

    record = {
        "id": REGULAR["slug"],
        "title": REGULAR["title"],
        "location": "Herisau / Winterthur, Switzerland",
        "employment_type": "80–100%",
        "listing_description": REGULAR["summary"],
        "url": f"https://www.clavisit.com{REGULAR['path']}",
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="clavis_it-platform-devops-engineer-kubernetes",
        added_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "clavis IT ag import"
    assert stored["company"] == "clavis IT ag"
