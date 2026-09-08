"""Validate usable job identities without requiring optional enrichment metadata."""

from urllib.parse import urlsplit

from app.models.parsers import ParsedJob, ParserSearchResponse

PARTIAL_PARSER_RESULT_PREFIX = "Parser returned partial results: "


def validate_parser_result(result: ParserSearchResponse) -> tuple[ParserSearchResponse, str | None]:
    """Keep usable vacancies and expose omitted records or failed detail enrichment.

    A title and public URL are required. Company, location, category, workload and
    description may be unavailable; their absence alone is not a parser failure.
    Source-specific catalog identity, country and completeness checks still run.
    """
    jobs: list[ParsedJob] = []
    issues = list(dict.fromkeys(warning.strip() for warning in result.warnings if warning.strip()))
    rejected = 0
    for job in result.jobs:
        try:
            url = urlsplit(job.url or "")
            valid_url = url.scheme in {"http", "https"} and bool(url.hostname)
        except ValueError:
            valid_url = False
        if not (job.title or "").strip() or not valid_url:
            rejected += 1
            issues.append(
                f"Skipped vacancy without a usable title or URL: {(job.url or job.title or 'unknown')[:300]}"
            )
            continue
        jobs.append(job)
        if detail_error := job.raw.get("detail_error"):
            issues.append(f"Details unavailable for {job.url}: {str(detail_error)[:500]}")

    if not issues:
        return result, None
    # Keep all diagnostics on the result; bound the persistent notification only.
    validated = result.model_copy(update={"jobs": jobs, "warnings": issues})
    details = "; ".join(issues[:5])
    if len(issues) > 5:
        details += f"; and {len(issues) - 5} more issues"
    message = (
        f"{PARTIAL_PARSER_RESULT_PREFIX}kept {len(jobs)} vacancies; "
        f"rejected {rejected} returned records; {len(issues)} issue(s). {details}"
    )
    return validated, message
