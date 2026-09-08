from datetime import UTC, datetime
from types import SimpleNamespace

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.job_search_execution import reconcile_full_catalog_inventory, run_status
from app.services.parser_validation import PARTIAL_PARSER_RESULT_PREFIX, validate_parser_result
from app.services.vacancy_search import VacancySearchRunner


def result_with(*jobs: ParsedJob, warnings: list[str] | None = None) -> ParserSearchResponse:
    return ParserSearchResponse(
        parser="sbb",
        status="completed",
        search_url="https://jobs.sbb.ch",
        jobs=list(jobs),
        warnings=warnings or [],
    )


def test_optional_job_metadata_does_not_fail_validation() -> None:
    result = result_with(ParsedJob(source="sbb", title="Engineer", url="https://jobs.sbb.ch/job/1"))
    validated, error = validate_parser_result(result)
    assert validated is result
    assert error is None
    assert validated.jobs[0].location is None
    assert validate_parser_result(result_with())[1] is None


def test_invalid_record_is_removed_but_detail_failure_preserves_usable_vacancy() -> None:
    result = result_with(
        ParsedJob(
            source="sbb",
            title="Engineer",
            url="https://jobs.sbb.ch/job/1",
            raw={"detail_error": "HTTP 503"},
        ),
        ParsedJob(source="sbb", title="", url="https://jobs.sbb.ch/job/2"),
        ParsedJob(source="sbb", title="Unsafe URL", url="javascript:alert(1)"),
    )
    validated, error = validate_parser_result(result)
    assert len(validated.jobs) == 1
    assert len(result.jobs) == 3  # Shared parser responses are not mutated.
    assert error.startswith(PARTIAL_PARSER_RESULT_PREFIX)
    assert "HTTP 503" in error
    assert "rejected 2" in error
    assert len(validated.warnings) == 3


def test_partial_catalog_warns_once_retains_jobs_and_does_not_expire_inventory(monkeypatch) -> None:
    calls = []

    class Parser:
        def search(self, request):
            calls.append(request)
            return result_with(
                ParsedJob(source="sbb", title="Engineer", url="https://jobs.sbb.ch/job/1"),
                warnings=["Skipped vacancy: country could not be verified"],
            )

    result = VacancySearchRunner({"sbb": Parser()}).run(
        sources=["sbb"], request=LinkedInSearchRequest()
    )
    assert len(calls) == 1
    assert result.source_attempts == {"sbb": 1}
    assert len(result.jobs) == 1
    assert "could not be verified" in result.source_errors["sbb"]
    assert run_status(result) == "partial"
    expired = []
    monkeypatch.setattr(
        "app.services.job_search_execution.mark_missing_vacancies_inactive",
        lambda *args, **kwargs: expired.append(kwargs),
    )
    reconcile_full_catalog_inventory(
        None,
        search_result=result,
        inventory_result=SimpleNamespace(vacancies=[]),
        unavailable_at=datetime.now(UTC),
    )
    assert expired == []
