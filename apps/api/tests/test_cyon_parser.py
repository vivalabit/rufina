from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.cyon import CyonJobsParser, normalize_job
from app.services.vacancy_search import create_vacancy_search_runner


class HtmlResponse:
    def __init__(self, page_html: str) -> None:
        self.selector = Selector(page_html)

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)

    def json(self) -> Any:
        raise AssertionError("cyon response is HTML")


def vacancy_section(
    job_id: str,
    section_id: str,
    title: str,
    *,
    workload: str = "80 - 100%",
    location: str = "Basel, Schweiz (Hybrid)",
    company_slug: str = "cyon-ag",
    fragment: str = "application",
    description: str = (
        "Du entwickelst nachhaltige Softwarelösungen für unsere Kundschaft. "
        "Du begleitest den gesamten Software-Lifecycle, schreibst sauberen Code "
        "und bringst neue Ideen in unser erfahrenes Team ein."
    ),
) -> str:
    application_slug = section_id.removesuffix("-80-100")
    return f"""
    <section x-data="cyon_accordion_item" id="{section_id}">
      <div x-bind="toggle"><div><h2>{title}</h2><p>{workload}</p></div></div>
      <div x-show="expanded">
        <ul>
          <li><span>Sofort oder nach Vereinbarung</span></li>
          <li><span>Pensum: {workload}</span></li>
          <li><span>Arbeitsort: {location}</span></li>
        </ul>
        <div class="prose-job"><h3>Über cyon</h3><p>{description}</p>
          <a href="https://my.jobalino.ch/job/{job_id}/{company_slug}/{application_slug}#{fragment}">
            bei uns
          </a>
        </div>
      </div>
    </section>
    """


def careers_html(sections: list[str], *, page_title: str | None = None) -> str:
    return f"""
    <html lang="de-CH"><head>
      <title>{page_title or "Arbeiten bei cyon | Freude, Passion und Teamgeist"}</title>
      <link rel="canonical" href="https://www.cyon.ch/ueber-cyon/jobs">
    </head><body><main>
      <h2>Stellenangebote</h2><h3>Offene Stellen bei cyon</h3>
      <div x-data="cyon_accordion">{"".join(sections)}</div>
    </main></body></html>
    """


def official_sections() -> list[str]:
    return [
        vacancy_section(
            "d46bed06fa68418c88ef3d14927e138a",
            "senior-software-engineer-alle-80-100",
            "Senior Software Engineer (alle) | 80-100%",
        ),
        vacancy_section(
            "1c6bed06fa68418c88ef3d14927e138b",
            "customer-support-agent-alle-80-100",
            "Customer Support Agent (alle) | 80-100%",
        ),
    ]


def test_cyon_module_import_does_not_initialize_browser_fetcher() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.services.parsers.companies.cyon; "
                "assert 'scrapling.fetchers' not in sys.modules"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_cyon_scans_complete_browser_rendered_catalog() -> None:
    calls: list[str] = []

    def fetch_page(url: str) -> HtmlResponse:
        calls.append(url)
        return HtmlResponse(careers_html(official_sections()))

    result = CyonJobsParser(fetch_page=fetch_page).search(LinkedInSearchRequest(results_limit=1))

    assert calls == ["https://www.cyon.ch/ueber-cyon/jobs"]
    assert result.message == (
        "Scanned 2 cyon vacancies from the complete JavaScript-protected careers catalog"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "cyon"
    assert first.title == "Senior Software Engineer (alle) | 80-100%"
    assert first.company == "cyon AG"
    assert first.location == "Basel, Schweiz (Hybrid)"
    assert first.employment_type == "80 - 100%"
    assert first.seniority == "Senior"
    assert first.description and first.description.startswith("Über cyon Du entwickelst")
    assert first.url == ("https://www.cyon.ch/ueber-cyon/jobs#senior-software-engineer-alle-80-100")
    assert first.apply_url == (
        "https://my.jobalino.ch/job/d46bed06fa68418c88ef3d14927e138a/"
        "cyon-ag/senior-software-engineer-alle#application"
    )
    assert first.raw["id"] == "d46bed06fa68418c88ef3d14927e138a"
    assert first.raw["starts_at"] == "Sofort oder nach Vereinbarung"


def test_cyon_rejects_wrong_page_identity_and_missing_catalog() -> None:
    wrong_identity = CyonJobsParser(
        fetch_page=lambda _: HtmlResponse(careers_html([], page_title="Generic careers"))
    )
    missing_catalog = CyonJobsParser(
        fetch_page=lambda _: HtmlResponse(
            careers_html([]).replace('<div x-data="cyon_accordion"></div>', "")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        wrong_identity.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="missing its official catalog"):
        missing_catalog.search(LinkedInSearchRequest())


@pytest.mark.parametrize(
    "section",
    [
        vacancy_section(
            "d46bed06fa68418c88ef3d14927e138a",
            "senior-software-engineer-alle-80-100",
            "Senior Software Engineer",
            location="Berlin, Deutschland",
        ),
        vacancy_section(
            "d46bed06fa68418c88ef3d14927e138a",
            "senior-software-engineer-alle-80-100",
            "Senior Software Engineer",
            company_slug="other-company",
        ),
        vacancy_section(
            "d46bed06fa68418c88ef3d14927e138a",
            "senior-software-engineer-alle-80-100",
            "Senior Software Engineer",
            fragment="details",
        ),
    ],
)
def test_cyon_rejects_out_of_scope_vacancies(section: str) -> None:
    parser = CyonJobsParser(fetch_page=lambda _: HtmlResponse(careers_html([section])))
    with pytest.raises(DirectCompanyRequestError, match="out-of-scope"):
        parser.search(LinkedInSearchRequest())


def test_cyon_rejects_duplicate_and_oversized_catalogs() -> None:
    section = official_sections()[0]
    duplicate = CyonJobsParser(fetch_page=lambda _: HtmlResponse(careers_html([section, section])))
    oversized = CyonJobsParser(
        max_jobs=1,
        fetch_page=lambda _: HtmlResponse(careers_html(official_sections())),
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        duplicate.search(LinkedInSearchRequest())
    with pytest.raises(DirectCompanyRequestError, match="configured limit of 1"):
        oversized.search(LinkedInSearchRequest())


def test_cyon_accepts_explicit_empty_catalog() -> None:
    result = CyonJobsParser(fetch_page=lambda _: HtmlResponse(careers_html([]))).search(
        LinkedInSearchRequest()
    )

    assert result.jobs == []
    assert result.message.startswith("Scanned 0 cyon vacancies")


def test_cyon_wraps_request_failures() -> None:
    def fail(_: str) -> HtmlResponse:
        raise RuntimeError("browser unavailable")

    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        CyonJobsParser(fetch_page=fail).search(LinkedInSearchRequest())


def test_cyon_is_registered_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["cyon"]

    assert isinstance(parser, CyonJobsParser)
    assert parser.base_url == settings.cyon_jobs_base_url
    assert parser.timeout_seconds == settings.cyon_jobs_timeout_seconds
    assert parser.max_jobs == settings.cyon_jobs_max_jobs
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "cyon", "filters": {}},
            "sources": ["cyon", "cyon"],
        }
    )
    assert request.sources == ["cyon"]


def test_cyon_jobs_render_as_direct_company_imports() -> None:
    record = {
        "id": "d46bed06fa68418c88ef3d14927e138a",
        "title": "Senior Software Engineer (alle) | 80-100%",
        "company": "cyon AG",
        "location": "Basel, Schweiz (Hybrid)",
        "employment_type": "80 - 100%",
        "description": "Build reliable hosting software.",
        "url": "https://www.cyon.ch/ueber-cyon/jobs#senior-software-engineer-alle-80-100",
        "apply_url": (
            "https://my.jobalino.ch/job/d46bed06fa68418c88ef3d14927e138a/"
            "cyon-ag/senior-software-engineer-alle#application"
        ),
    }
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="cyon-d46bed06fa68418c88ef3d14927e138a",
        added_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "cyon AG import"
    assert stored["company"] == "cyon AG"
