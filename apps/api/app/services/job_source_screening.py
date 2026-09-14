"""Keep source-specific experience filters independent when vacancies are deduplicated."""

from typing import get_args

from app.models.job_search import ScreeningConfig, ScreeningSeniority
from app.models.parsers import ParsedJob
from app.services.vacancy_search import canonical_job_url, job_identity

SENIORITY_LEVELS: tuple[ScreeningSeniority, ...] = get_args(ScreeningSeniority)
SOURCE_SPECIFIC_FIELDS = {"enabled", "allowed_seniority"}


def screening_policies_for_jobs(
    jobs: list[ParsedJob],
    *,
    source_jobs: list[ParsedJob],
    default_policy: ScreeningConfig,
    source_policies: dict[str, ScreeningConfig],
) -> list[ScreeningConfig]:
    """Resolve one policy per job, admitting an experience level from any matching source.

    ``source_jobs`` must contain only date-filtered source results. URL and identity
    membership follows the same matching rules as ``deduplicate_jobs``. Common
    screening criteria remain unchanged; only source experience constraints vary.
    """
    sources_by_url: dict[str, set[str]] = {}
    sources_by_identity: dict[str, set[str]] = {}
    for job in source_jobs:
        url = canonical_job_url(job.url)
        identity = job_identity(job)
        if url:
            sources_by_url.setdefault(url, set()).add(job.source)
        if identity:
            sources_by_identity.setdefault(identity, set()).add(job.source)

    policies: list[ScreeningConfig] = []
    for job in jobs:
        sources = {
            job.source,
            *sources_by_url.get(canonical_job_url(job.url), ()),
            *sources_by_identity.get(job_identity(job), ()),
        }
        alternatives = [source_policies.get(source, default_policy) for source in sorted(sources)]
        policies.append(combine_source_experience_policies(alternatives))
    return policies


def combine_source_experience_policies(policies: list[ScreeningConfig]) -> ScreeningConfig:
    """Represent the OR of source experience filters without widening shared criteria."""
    first = policies[0]
    common_criteria = first.model_dump(exclude=SOURCE_SPECIFIC_FIELDS)
    if any(
        policy.model_dump(exclude=SOURCE_SPECIFIC_FIELDS) != common_criteria for policy in policies
    ):
        raise ValueError("Cannot combine source screening policies with different shared criteria")

    # A source which does not screen admits the vacancy regardless of experience.
    # The shared-criteria guard runs first so a future policy cannot bypass global rules.
    disabled = next((policy for policy in policies if not policy.enabled), None)
    if disabled is not None:
        return disabled
    if len(policies) == 1:
        return first

    allowed = (
        set().union(*(set(policy.allowed_seniority) for policy in policies))
        if all(policy.allowed_seniority for policy in policies)
        else set()
    )
    return first.model_copy(
        update={
            "allowed_seniority": [level for level in SENIORITY_LEVELS if level in allowed],
        }
    )
