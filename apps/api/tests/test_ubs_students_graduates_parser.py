from __future__ import annotations

import html
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
from app.services.parsers.companies.ubs_students_graduates import (
    UbsStudentsGraduatesJobsParser,
    normalize_job,
)
from app.services.vacancy_search import create_vacancy_search_runner


def question(
    name: str,
    value: str,
    *,
    actual: str | None = None,
) -> dict[str, object]:
    return {
        "QuestionName": name,
        "Value": value,
        "ActualValueFromSolar": actual if actual is not None else value,
    }


def listing_record(
    *,
    job_id: str,
    title: str,
    location: str,
    updated_at: str,
) -> dict[str, object]:
    return {
        "Questions": [
            question("reqid", job_id),
            question("siteid", "5131"),
            question("jobtitle", title),
            question("formtext23", location),
            question("formtext21", "Information Technology (IT)"),
            question("department", "Group Functions"),
            question(
                "lastupdated",
                "04-Aug-2026",
                actual=f"{updated_at}T00:00:00Z",
            ),
            question("jobdescription", f"Short description for {title}."),
        ],
        "Link": (
            "https://jobs.ubs.test/TGnewUI/Search/home/HomeWithPreLoad?"
            f"partnerid=25008&siteid=5131&PageType=JobDetails&jobid={job_id}"
        ),
    }


def search_response(
    records: list[dict[str, object]],
    *,
    total_count: int,
    page_size: int = 2,
) -> dict[str, object]:
    return {
        "Jobs": {"Job": records},
        "JobsCount": total_count,
        "PageSize": page_size,
        "SortFields": [
            {"Name": "LastUpdated", "Value": "Date"},
            {"Name": "JobTitle", "Value": "Alphabetical"},
        ],
    }


def preload_html(
    *,
    response: dict[str, object] | None = None,
    detail: dict[str, object] | None = None,
) -> str:
    smart = {
        "PartnerId": 25008,
        "SiteId": 5131,
        "EncryptedSessionValue": "encrypted-session",
        "KeywordCustomSolrFields": "FORMTEXT21,AutoReq,Department,JobTitle",
        "LocationCustomSolrFields": "FORMTEXT2,FORMTEXT23,Location",
    }
    payload = {
        "SmartSearchJSONValue": json.dumps(smart),
        "searchResultsResponse": response,
        "Jobdetails": detail,
    }
    encoded = html.escape(json.dumps(payload), quote=True)
    return (
        f'<html><body><input id="preLoadJSON" value="{encoded}">'
        '<input id="linkId" value="15232"></body></html>'
    )


def detail_payload(*, job_id: str, title: str) -> dict[str, object]:
    def detail_question(zone: str, label: str, value: str) -> dict[str, str]:
        return {
            "VerityZone": zone,
            "QuestionName": label,
            "AnswerValue": value,
        }

    return {
        "Title": title,
        "Link": (
            "https://jobs.ubs.test/TGnewUI/Search/home/HomeWithPreLoad?"
            f"partnerid=25008&siteid=5131&PageType=JobDetails&jobid={job_id}"
        ),
        "JobDetailQuestions": [
            detail_question("reqid", "", job_id),
            detail_question("lastupdated", "", "04-Aug-2026"),
            detail_question("jobtitle", "Title", title),
            detail_question("formtext23", "Country / State", "Switzerland - Zürich"),
            detail_question("formtext2", "City", "Zürich"),
            detail_question("formtext21", "Function Category", "Technology"),
            detail_question("department", "Business Divisions", "Group Functions"),
            detail_question("autoreq", "Job Reference #", "123456BR"),
            detail_question(
                "jobdescription",
                "Your role",
                "Build useful tools.<br>• Support the team",
            ),
            detail_question("formtext58", "Your team", "A collaborative team."),
            detail_question("formtext59", "Your expertise", "Curious students."),
            detail_question("formtext63", "Your program", "A paid internship."),
        ],
    }


def test_ubs_students_graduates_scans_all_pages_and_filters_switzerland() -> None:
    swiss_one = listing_record(
        job_id="349179",
        title="2026 Off-cycle Internship – Governmental Affairs – Zurich",
        location="Switzerland - Zürich",
        updated_at="2026-08-04",
    )
    luxembourg = listing_record(
        job_id="348796",
        title="Intern in Wealth Management (6 months)",
        location="Luxembourg",
        updated_at="2026-08-03",
    )
    swiss_two = listing_record(
        job_id="347766",
        title="2026 Off-cycle Internship - Data Management",
        location="Switzerland - Zürich",
        updated_at="2026-07-30",
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = parse_qs(request.url.query.decode())
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["pageNumber"] == 2
            assert payload["linkId"] == "15232"
            assert payload["SortType"] == "LastUpdated"
            assert payload["encryptedSessionValue"] == "encrypted-session"
            return httpx.Response(
                200,
                json=search_response([swiss_two], total_count=3),
            )
        if query.get("PageType") == ["JobDetails"]:
            job_id = query["jobid"][0]
            title = (
                swiss_one["Questions"][2]["Value"]
                if job_id == "349179"
                else swiss_two["Questions"][2]["Value"]
            )
            return httpx.Response(
                200,
                text=preload_html(
                    detail=detail_payload(job_id=job_id, title=str(title)),
                ),
            )
        assert query["LinkID"] == ["15232"]
        return httpx.Response(
            200,
            text=preload_html(
                response=search_response(
                    [swiss_one, luxembourg],
                    total_count=3,
                )
            ),
        )

    parser = UbsStudentsGraduatesJobsParser(
        base_url=(
            "https://jobs.ubs.test/TGnewUI/Search/home/HomeWithPreLoad?"
            "partnerid=25008&siteid=5131&PageType=searchResults&"
            "SearchType=linkquery&LinkID=15232"
            "#keyWordSearch=&locationSearch=Switzerland"
        ),
        api_url=(
            "https://jobs.ubs.test/TgNewUI/Search/Ajax/"
            "ProcessSortAndShowMoreJobs"
        ),
        detail_workers=2,
        transport=httpx.MockTransport(handler),
    )

    result = parser.search(LinkedInSearchRequest(results_limit=1))

    assert len(requests) == 4
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 UBS Students & Graduates vacancies in Switzerland"
    )
    assert len(result.jobs) == 2
    first = result.jobs[0]
    assert first.source == "ubs_students_graduates"
    assert first.company == "UBS"
    assert first.title == (
        "2026 Off-cycle Internship – Governmental Affairs – Zurich"
    )
    assert first.location == "Switzerland - Zürich"
    assert first.posted_at == "2026-08-04"
    assert first.employment_type == "Internship"
    assert first.seniority == "Internship"
    assert first.apply_url == first.url
    assert first.description == (
        "Your role\n\nBuild useful tools.\n• Support the team\n\n"
        "Your team\n\nA collaborative team.\n\n"
        "Your expertise\n\nCurious students.\n\n"
        "Your program\n\nA paid internship."
    )
    assert first.raw["detail"]["reference"] == "123456BR"


def test_ubs_students_graduates_preserves_listing_when_detail_fails() -> None:
    record = listing_record(
        job_id="349179",
        title="2026 Off-cycle Internship – Governmental Affairs – Zurich",
        location="Switzerland - Zürich",
        updated_at="2026-08-04",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        if query.get("PageType") == ["JobDetails"]:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            text=preload_html(
                response=search_response([record], total_count=1, page_size=50)
            ),
        )

    parser = UbsStudentsGraduatesJobsParser(
        transport=httpx.MockTransport(handler),
        detail_workers=1,
    )

    job = parser.search(LinkedInSearchRequest()).jobs[0]

    assert job.title == record["Questions"][2]["Value"]
    assert job.posted_at == "2026-08-04"
    assert job.description == f"Short description for {job.title}."
    assert job.apply_url == job.url
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_ubs_students_graduates_rejects_missing_preload_contract() -> None:
    parser = UbsStudentsGraduatesJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<html><body>Changed</body></html>")
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="missing the preloaded JSON"):
        parser.search(LinkedInSearchRequest())


def test_ubs_students_graduates_rejects_duplicate_vacancy_ids() -> None:
    record = listing_record(
        job_id="349179",
        title="2026 Off-cycle Internship – Governmental Affairs – Zurich",
        location="Switzerland - Zürich",
        updated_at="2026-08-04",
    )
    parser = UbsStudentsGraduatesJobsParser(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=preload_html(
                    response=search_response([record, record], total_count=2)
                ),
            )
        )
    )

    with pytest.raises(DirectCompanyRequestError, match="duplicate vacancy IDs"):
        parser.search(LinkedInSearchRequest())


def test_ubs_students_graduates_enforces_page_limit() -> None:
    record = listing_record(
        job_id="349179",
        title="2026 Off-cycle Internship – Governmental Affairs – Zurich",
        location="Switzerland - Zürich",
        updated_at="2026-08-04",
    )
    parser = UbsStudentsGraduatesJobsParser(
        max_pages=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                text=preload_html(
                    response=search_response(
                        [record],
                        total_count=101,
                        page_size=50,
                    )
                ),
            )
        ),
    )

    with pytest.raises(DirectCompanyRequestError, match="configured page limit"):
        parser.search(LinkedInSearchRequest())


def test_ubs_students_graduates_is_registered_as_direct_company_source() -> None:
    settings = Settings()
    runner = create_vacancy_search_runner(settings)

    parser = runner.parsers["ubs_students_graduates"]
    assert isinstance(parser, UbsStudentsGraduatesJobsParser)
    assert parser.base_url == settings.ubs_students_graduates_jobs_base_url
    assert parser.api_url == settings.ubs_students_graduates_jobs_api_url
    assert parser.max_pages == settings.ubs_students_graduates_jobs_max_pages
    assert parser.detail_workers == settings.ubs_students_graduates_jobs_detail_workers
    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "UBS Students & Graduates", "filters": {}},
            "sources": ["ubs_students_graduates", "ubs_students_graduates"],
        }
    )
    assert request.sources == ["ubs_students_graduates"]


def test_ubs_students_graduates_jobs_render_as_direct_company_imports() -> None:
    record = listing_record(
        job_id="349179",
        title="2026 Off-cycle Internship – Governmental Affairs – Zurich",
        location="Switzerland - Zürich",
        updated_at="2026-08-04",
    )
    stored = parsed_job_to_stored_job(
        normalize_job(record),
        job_id="ubs_students_graduates-349179",
        added_at=datetime.now(UTC),
    )

    assert stored["logo"] == "company"
    assert stored["department"] == "UBS Students & Graduates import"
    assert stored["id"] == "ubs_students_graduates-349179"
