from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from scrapling import Selector

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.sbb import SbbJobsParser, page_start_items
from app.services.vacancy_search import create_vacancy_search_runner

LANDING_HTML = """
<html>
  <body>
    <div
      data-init="jobfilter"
      data-jobfilter-api="/content/jobfilter.results.json"
    ></div>
  </body>
</html>
"""


class HtmlResponse:
    def __init__(self, html: str) -> None:
        self.selector = Selector(html)

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        return self.selector.css(selector, *args, **kwargs)

    def json(self) -> Any:
        raise AssertionError("HTML response is not JSON")


class JsonResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"JSON response does not support CSS: {selector}")

    def json(self) -> Any:
        return self.payload


def sbb_record(index: int) -> dict[str, Any]:
    return {
        "id": f"job-{index}",
        "viewkey": f"view-{index}",
        "title": f"Platform Engineer {index}",
        "attributes": {
            "20": ["IT / Telekommunikation"],
            "50": ["Vollzeit", "Teilzeit"],
            "60": ["Berufserfahrene"],
            "65": ["Schweiz"],
            "100": ["Bern"],
            "110": ["Bern Mittelland (BE/SO/AG)"],
            "130": ["true"],
            "160": ["60-100%"],
        },
        "links": {"directlink": f"https://jobs.sbb.ch/v2/offene-stellen/job-{index}/view-{index}"},
        "start_date": "2026-07-31T07:23:16Z",
    }


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, []),
        (1, [1]),
        (10, [1]),
        (11, [1, 11]),
        (99, [1, 11, 21, 31, 41, 51, 61, 71, 81, 91]),
        (138, [1, 11, 21, 31, 41, 51, 61, 71, 81, 91, 101, 111, 121, 131]),
    ],
)
def test_page_start_items_stops_on_the_page_containing_the_last_job(
    total: int,
    expected: list[int],
) -> None:
    assert page_start_items(total) == expected


def test_sbb_parser_extracts_total_and_partitions_all_records_into_ten_job_pages() -> None:
    calls: list[str] = []
    records = [sbb_record(index) for index in range(23)]

    def fetch_page(url: str) -> HtmlResponse | JsonResponse:
        calls.append(url)
        return (
            JsonResponse(records)
            if url.endswith("jobfilter.results.json")
            else HtmlResponse(LANDING_HTML)
        )

    parser = SbbJobsParser(
        base_url="https://company.sbb.test/de/offene-stellen.html",
        fetch_page=fetch_page,
    )

    result = parser.search(LinkedInSearchRequest(results_limit=5))

    assert calls == [
        "https://company.sbb.test/de/offene-stellen.html?startItem=1",
        "https://company.sbb.test/content/jobfilter.results.json",
    ]
    assert result.status == "completed"
    assert len(result.jobs) == 23
    assert result.message == "Scanned 23 SBB vacancies across 3 logical pages"
    assert result.jobs[0].company == "SBB CFF FFS"
    assert result.jobs[0].location == "Bern"
    assert result.jobs[0].employment_type == "Vollzeit, Teilzeit"
    assert result.jobs[0].seniority == "Berufserfahrene"
    assert result.jobs[0].description == (
        "Tätigkeitsgebiet: IT / Telekommunikation. "
        "Region: Bern Mittelland (BE/SO/AG). Pensum: 60-100%. "
        "Land: Schweiz. Work Smart: Ja"
    )
    assert result.jobs[0].raw["total_available"] == 23
    assert result.jobs[9].raw["listing_page_url"].endswith("startItem=1")
    assert result.jobs[10].raw["listing_page_url"].endswith("startItem=11")
    assert result.jobs[22].raw["listing_page_url"].endswith("startItem=21")


def test_sbb_parser_surfaces_invalid_jobfilter_payload_as_source_error() -> None:
    def fetch_page(url: str) -> HtmlResponse | JsonResponse:
        return (
            JsonResponse({"jobs": []})
            if "jobfilter.results.json" in url
            else HtmlResponse(LANDING_HTML)
        )

    parser = SbbJobsParser(fetch_page=fetch_page)

    with pytest.raises(DirectCompanyRequestError, match="must be a list"):
        parser.search(LinkedInSearchRequest())


def test_sbb_is_registered_as_a_direct_company_source() -> None:
    runner = create_vacancy_search_runner(Settings())

    assert isinstance(runner.parsers["sbb"], SbbJobsParser)
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "SBB", "filters": {}},
            "sources": ["sbb", "sbb"],
        }
    )
    assert request.sources == ["sbb"]


def test_sbb_jobs_render_as_direct_company_imports() -> None:
    job = SbbJobsParser.normalize_job(
        SbbJobsParser(fetch_page=lambda _: HtmlResponse(LANDING_HTML)),
        sbb_record(1),
        listing_page_url="https://company.sbb.test/jobs?startItem=1",
        total_available=1,
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="sbb-view-1",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "SBB CFF FFS import"
