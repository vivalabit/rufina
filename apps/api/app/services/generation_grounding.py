"""Final check that a tailored document only presents facts of its frozen profile."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.resume import (
    FinalResume,
    MasterExperience,
    MasterResume,
    ResumeEvidence,
)
from app.services.ats.wording import language_code
from app.services.resume_skills import (
    CORE_SKILL_CATEGORIES,
    order_skill_categories,
    source_skill_category,
)


class GenerationGroundingError(ValueError):
    pass


def _skill_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def validate_grounded_bundle(
    bundle: DraftBundle,
    *,
    master_resume: MasterResume,
    target_job_id: str,
) -> None:
    canonical_evidence = {item.id: item for item in master_resume.evidence}
    if bundle.resume is not None:
        _validate_resume(
            bundle.resume,
            master_resume=master_resume,
            target_job_id=target_job_id,
            canonical_evidence=canonical_evidence,
        )
    if bundle.cover_letter is not None:
        _validate_cover_letter(
            bundle.cover_letter,
            target_job_id=target_job_id,
            canonical_evidence=canonical_evidence,
        )


def _validate_resume(
    resume: FinalResume,
    *,
    master_resume: MasterResume,
    target_job_id: str,
    canonical_evidence: dict[str, ResumeEvidence],
) -> None:
    if resume.master_resume_id != master_resume.id or resume.target_job_id != target_job_id:
        raise GenerationGroundingError("Tailored resume is linked to the wrong source snapshot")
    for evidence in resume.evidence:
        original = canonical_evidence.get(evidence.id)
        if original is None or evidence != original:
            raise GenerationGroundingError(
                f"Tailored resume contains non-canonical evidence: {evidence.id}"
            )

    experience_by_id = {item.id: item for item in master_resume.experiences}
    # A resume in another language than its profile shows translated job titles.
    translated = language_code(resume.language) != language_code(master_resume.language)
    for item in resume.experiences:
        original = experience_by_id.get(item.master_experience_id)
        if original is None:
            raise GenerationGroundingError(
                f"Tailored resume references unknown experience: {item.master_experience_id}"
            )
        if item.company != original.company or (
            item.title != original.title and not (translated and item.title.strip())
        ):
            raise GenerationGroundingError(
                f"Tailored resume changed protected employer or title: {original.id}"
            )
        if not _period_matches_source(item.period, original):
            raise GenerationGroundingError(
                f"Tailored resume changed protected role dates: {original.id}"
            )

        for bullet in item.bullets:
            for evidence_id in bullet.evidence_ids:
                evidence = canonical_evidence.get(evidence_id)
                if evidence and evidence.experience_id and evidence.experience_id != original.id:
                    raise GenerationGroundingError(
                        f"Tailored resume moved evidence from another employer: {evidence_id}"
                    )

    source_roles = [item.id for item in master_resume.experiences]
    resume_roles = [item.master_experience_id for item in resume.experiences]
    if resume_roles != source_roles:
        raise GenerationGroundingError(
            "Tailored resume must retain every source experience in its original order"
        )
    if resume.languages != master_resume.languages:
        raise GenerationGroundingError(
            "Tailored resume must retain all source languages and proficiency levels"
        )
    skill_names = {_skill_key(item.name) for item in resume.skills}
    missing_skills = [
        item.name for item in master_resume.skills
        if source_skill_category(item) in CORE_SKILL_CATEGORIES
        and _skill_key(item.name) not in skill_names
    ]
    if missing_skills:
        raise GenerationGroundingError(
            f"Tailored resume omitted core source skills: {missing_skills}"
        )
    if resume.skills != order_skill_categories(resume.skills):
        raise GenerationGroundingError("Tailored resume changed the required Skills category order")


def _validate_cover_letter(
    letter: CoverLetterDraft,
    *,
    target_job_id: str,
    canonical_evidence: dict[str, ResumeEvidence],
) -> None:
    if letter.target_job_id != target_job_id:
        raise GenerationGroundingError("Cover letter is linked to the wrong vacancy")
    referenced = {
        evidence_id for paragraph in letter.paragraphs for evidence_id in paragraph.evidence_ids
    }
    unknown = sorted(referenced - set(canonical_evidence))
    if unknown:
        raise GenerationGroundingError(f"Cover letter references unknown evidence IDs: {unknown}")


_MONTH_NUMBERS = {
    name.casefold(): month
    for month, names in enumerate(
        (
            ("Jan", "January", "Januar"),
            ("Feb", "February", "Februar"),
            ("Mar", "March", "Mär", "März", "Maerz"),
            ("Apr", "April"),
            ("May", "Mai"),
            ("Jun", "June", "Juni"),
            ("Jul", "July", "Juli"),
            ("Aug", "August"),
            ("Sep", "Sept", "September"),
            ("Oct", "October", "Okt", "Oktober"),
            ("Nov", "November"),
            ("Dec", "December", "Dez", "Dezember"),
        ),
        start=1,
    )
    for name in names
}
_CURRENT_MARKERS = {
    "present", "current", "now", "ongoing", "today", "heute", "aktuell", "présent", "aujourd'hui",
}
# Shown for a role whose profile entry has no dates at all.
_UNDATED_PERIOD = "–"
_RANGE_SEPARATOR = re.compile(r"[-‐‑‒–—―−]|\b(?:to|bis)\b")


def _date_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _date_parts(value: str) -> tuple[int, ...] | None:
    """Parse only explicit dates, retaining their year/month/day precision."""
    if re.fullmatch(r"\d{4}", value):
        year = int(value)
        return (year,) if 1 <= year <= 9999 else None
    parts: tuple[int, ...]
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", value):
        parts = tuple(int(part) for part in match.groups() if part is not None)
    elif match := re.fullmatch(r"(\d{1,2})[/.](\d{4})", value):
        parts = (int(match[2]), int(match[1]))
    elif match := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value):
        parts = (int(match[3]), int(match[2]), int(match[1]))
    elif match := re.fullmatch(r"([^\W\d_]+)\.? (\d{4})", value):
        month = _MONTH_NUMBERS.get(match[1])
        if month is None:
            return None
        parts = (int(match[2]), month)
    else:
        return None
    try:
        date(parts[0], parts[1], parts[2] if len(parts) == 3 else 1)
    except ValueError:
        return None
    return parts


def _same_date(actual: str, expected: str) -> bool:
    actual, expected = _date_text(actual), _date_text(expected)
    if actual == expected:
        return True
    expected_parts = _date_parts(expected)
    return expected_parts is not None and _date_parts(actual) == expected_parts


def _period_matches_source(period: str, experience: MasterExperience) -> bool:
    """Allow presentation changes, never different dates or reduced precision."""
    if not experience.start_date and not experience.end_date and not experience.is_current:
        return period.strip() == _UNDATED_PERIOD
    period = _date_text(period)

    def matches_end(value: str) -> bool:
        if experience.is_current:
            return _date_text(value) in _CURRENT_MARKERS
        return _same_date(value, experience.end_date)

    if not experience.start_date:
        return matches_end(period)
    if not experience.is_current and not experience.end_date:
        return _same_date(period, experience.start_date)
    # Try each separator rather than splitting ISO dates at their inner hyphens.
    # Both complete endpoints must match the source for any split to succeed.
    return any(
        _same_date(period[: separator.start()], experience.start_date)
        and matches_end(period[separator.end() :])
        for separator in _RANGE_SEPARATOR.finditer(period)
    )


__all__ = [
    "GenerationGroundingError",
    "validate_grounded_bundle",
]
