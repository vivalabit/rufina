"""Structured documents produced by a tailoring run."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.models.generation import GenerationContractModel
from app.models.resume import EvidenceId, FinalResume


class CoverLetterParagraphDraft(GenerationContractModel):
    text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: tuple[EvidenceId, ...] = Field(default=(), alias="evidenceIds")


class CoverLetterDraft(GenerationContractModel):
    id: str = Field(min_length=1, max_length=160)
    target_job_id: str = Field(min_length=1, max_length=160, alias="targetJobId")
    language: str = Field(min_length=1, max_length=40)
    recipient: str = Field(max_length=500)
    subject: str = Field(min_length=1, max_length=500)
    salutation: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[CoverLetterParagraphDraft, ...] = Field(min_length=2, max_length=12)
    closing: str = Field(min_length=1, max_length=500)
    signature: str = Field(min_length=1, max_length=500)


class DraftBundle(GenerationContractModel):
    """Renderable documents of one run, with evidence resolved by the server."""

    resume: FinalResume | None = None
    cover_letter: CoverLetterDraft | None = Field(default=None, alias="coverLetter")

    @model_validator(mode="after")
    def require_a_document(self) -> DraftBundle:
        if self.resume is None and self.cover_letter is None:
            raise ValueError("Draft bundle must contain at least one document")
        return self


__all__ = [
    "CoverLetterDraft",
    "CoverLetterParagraphDraft",
    "DraftBundle",
]
