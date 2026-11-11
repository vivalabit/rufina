from __future__ import annotations

import re
import unicodedata
from datetime import date

from app.models.generation_workflow import CoverLetterDraft, DraftBundle, GeneratedDraftBundle
from app.models.resume import (
    FinalResume,
    MasterExperience,
    MasterResume,
    MasterSkill,
    ResumeDraft,
    ResumeEvidence,
    resume_evidence_ids,
)
from app.services.resume_skills import (
    CORE_SKILL_CATEGORIES,
    normalize_skill_category,
    order_skill_categories,
    source_skill_category,
)

_GENERATED_SECTION_PRIORITY = {
    section: index
    for index, section in enumerate(("summary", "experience", "education", "languages", "skills"))
}


class GenerationGroundingError(ValueError):
    pass


def ground_generated_bundle(
    generated: GeneratedDraftBundle,
    *,
    master_resume: MasterResume,
    target_job_id: str,
) -> DraftBundle:
    """Preserve profile essentials and resolve references against the frozen source.

    Evidence is server-owned: model responses cannot supply or rewrite it.
    Keep source ordering for deterministic artifacts and copy entries so the
    materialized document cannot mutate the snapshot's catalog.
    """
    resume = None
    if generated.resume is not None:
        referenced = set(resume_evidence_ids(generated.resume))
        canonical_ids = {item.id for item in master_resume.evidence}
        unknown = sorted(referenced - canonical_ids)
        if unknown:
            raise GenerationGroundingError(
                f"Tailored resume references unknown evidence IDs: {unknown}"
            )
        preserved = _preserve_profile_sections(generated.resume, master_resume)
        referenced = set(resume_evidence_ids(preserved))
        resume = FinalResume.model_validate(
            {
                **preserved.model_dump(mode="json", by_alias=True),
                "evidence": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in master_resume.evidence
                    if item.id in referenced
                ],
            }
        )
    # Keep structured content, PDF verification and the sender block tied to
    # the same frozen identity, including when no CV is requested.
    letter = (
        generated.cover_letter.model_copy(update={"signature": master_resume.basics.full_name})
        if generated.cover_letter is not None else None
    )
    bundle = DraftBundle(resume=resume, cover_letter=letter)
    validate_grounded_bundle(
        bundle,
        master_resume=master_resume,
        target_job_id=target_job_id,
    )
    return bundle


def _skill_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _preserve_profile_sections(draft: ResumeDraft, master: MasterResume) -> ResumeDraft:
    """Apply the same lossless rules to authors, reviewer revisions and PDF repairs.

    Let the model choose vacancy-specific extra skills and priority within each
    category. Preserve the source's four core technical categories regardless
    of keyword matches, along with all spoken languages.
    Missing roles are rejected by validation rather than inventing replacement
    bullets. The source order is authoritative, even when it is not chronological.
    """
    order = {item.id: index for index, item in enumerate(master.experiences)}
    skills_by_id = {item.id: item for item in master.skills}
    skills_by_name = {_skill_key(item.name): item for item in reversed(master.skills)}
    skills: list[MasterSkill] = []
    seen: set[str] = set()
    for item in draft.skills:
        original = skills_by_id.get(item.id) or skills_by_name.get(_skill_key(item.name))
        if original is not None:
            # Core categories, names and evidence are canonical. Extra categories
            # can be tailored to the vacancy, without restoring unselected extras.
            source_category = source_skill_category(original)
            category = (
                source_category if source_category in CORE_SKILL_CATEGORIES
                else normalize_skill_category(item.category or original.category)
            )
            item = original.model_copy(deep=True, update={"category": category})
        else:
            # A skill may also be supported by a detailed role/project source.
            item = item.model_copy(
                deep=True, update={"category": normalize_skill_category(item.category)}
            )
        key = _skill_key(item.name)
        if key not in seen:
            skills.append(item)
            seen.add(key)
    for item in master.skills:
        key = _skill_key(item.name)
        category = source_skill_category(item)
        if category in CORE_SKILL_CATEGORIES and key not in seen:
            skills.append(item.model_copy(deep=True, update={"category": category}))
            seen.add(key)
    skills = order_skill_categories(skills)

    section_order = list(draft.section_order)
    for section, items in (("skills", skills), ("languages", master.languages)):
        if items and section not in section_order:
            following = (
                master.section_order[master.section_order.index(section) + 1 :]
                if section in master.section_order else []
            )
            next_section = next((name for name in following if name in section_order), None)
            index = section_order.index(next_section) if next_section else len(section_order)
            section_order.insert(index, section)
        elif not items and section in section_order:
            section_order.remove(section)

    # Keep the introduction first and the main sections in the product's order.
    # Stable sorting preserves the relative order of any remaining sections.
    section_order.sort(
        key=lambda section: _GENERATED_SECTION_PRIORITY.get(section, len(_GENERATED_SECTION_PRIORITY))
    )

    return draft.model_copy(
        deep=True,
        update={
            "experiences": sorted(
                draft.experiences,
                key=lambda item: order.get(item.master_experience_id, len(order)),
            ),
            "languages": [item.model_copy(deep=True) for item in master.languages],
            "skills": skills,
            "section_order": section_order,
        },
    )


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
    for item in resume.experiences:
        original = experience_by_id.get(item.master_experience_id)
        if original is None:
            raise GenerationGroundingError(
                f"Tailored resume references unknown experience: {item.master_experience_id}"
            )
        if item.company != original.company or item.title != original.title:
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
_CURRENT_MARKERS = {"present", "current", "now", "ongoing", "today", "heute", "aktuell"}
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
    "ground_generated_bundle",
    "validate_grounded_bundle",
]
