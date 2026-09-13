from __future__ import annotations

from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.resume import FinalResume, MasterExperience, MasterResume, ResumeEvidence


class GenerationGroundingError(ValueError):
    pass


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
        if item.period not in _accepted_periods(original):
            raise GenerationGroundingError(
                f"Tailored resume changed protected role dates: {original.id}"
            )


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


def _accepted_periods(experience: MasterExperience) -> set[str]:
    end = "Present" if experience.is_current else experience.end_date
    if not experience.start_date:
        return {end} if end else {""}
    if not end:
        return {experience.start_date}
    return {
        f"{experience.start_date} - {end}",
        f"{experience.start_date} – {end}",
        f"{experience.start_date} — {end}",
    }


__all__ = ["GenerationGroundingError", "validate_grounded_bundle"]
