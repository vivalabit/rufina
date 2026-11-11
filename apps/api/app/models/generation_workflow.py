from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.models.generation import GenerationContractModel
from app.models.resume import EvidenceId, FinalResume, ResumeDraft


class FitKeyword(GenerationContractModel):
    term: str = Field(min_length=1, max_length=240)
    importance: Literal["required", "preferred"]
    support: Literal["supported", "synonym", "gap"]
    evidence_ids: tuple[EvidenceId, ...] = Field(default=(), alias="evidenceIds")


class FitEvaluation(GenerationContractModel):
    eligible: bool
    overall_score: int = Field(alias="overallScore", ge=0, le=100)
    recommendation: Literal["strong_yes", "yes", "consider", "no"]
    summary: str = Field(min_length=1, max_length=4_000)
    strengths: tuple[str, ...] = Field(max_length=20)
    gaps: tuple[str, ...] = Field(max_length=20)
    keywords: tuple[FitKeyword, ...] = Field(max_length=100)
    clarification_questions: tuple[str, ...] = Field(
        default=(), max_length=10, alias="clarificationQuestions"
    )


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


class GeneratedDraftBundle(GenerationContractModel):
    """Model response: document content and evidence IDs, without an evidence catalog."""

    resume: ResumeDraft | None = None
    cover_letter: CoverLetterDraft | None = Field(default=None, alias="coverLetter")

    @model_validator(mode="after")
    def require_a_document(self) -> GeneratedDraftBundle:
        if self.resume is None and self.cover_letter is None:
            raise ValueError("Draft bundle must contain at least one document")
        return self


class DraftBundle(GeneratedDraftBundle):
    """Persisted/renderable documents with evidence resolved by the server."""

    resume: FinalResume | None = None


class ReviewFinding(GenerationContractModel):
    severity: Literal["blocking", "warning", "suggestion"]
    category: Literal[
        "grounding",
        "requirements",
        "company",
        "tone",
        "consistency",
        "clarity",
    ]
    document: Literal["resume", "cover_letter", "both"]
    message: str = Field(min_length=1, max_length=2_000)
    suggested_change: str = Field(default="", max_length=2_000, alias="suggestedChange")


class CompanyResearchSource(GenerationContractModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2_000)
    note: str = Field(min_length=1, max_length=1_000)


class ReviewerFeedback(GenerationContractModel):
    approved: bool
    summary: str = Field(min_length=1, max_length=4_000)
    findings: tuple[ReviewFinding, ...] = Field(max_length=50)
    meaningful_changes: tuple[str, ...] = Field(
        default=(), max_length=20, alias="meaningfulChanges"
    )
    company_sources: tuple[CompanyResearchSource, ...] = Field(
        default=(), max_length=20, alias="companySources"
    )


class ReviewedDraftBundle(GenerationContractModel):
    draft: DraftBundle
    review: ReviewerFeedback


class VisualReviewFinding(GenerationContractModel):
    document: Literal["resume", "cover_letter"]
    page: int = Field(ge=1)
    severity: Literal["blocking", "warning", "suggestion"]
    message: str = Field(min_length=1, max_length=2_000)


class VisualReview(GenerationContractModel):
    approved: bool
    summary: str = Field(min_length=1, max_length=4_000)
    findings: tuple[VisualReviewFinding, ...] = Field(max_length=50)


__all__ = [
    "CompanyResearchSource",
    "CoverLetterDraft",
    "CoverLetterParagraphDraft",
    "DraftBundle",
    "FitEvaluation",
    "FitKeyword",
    "GeneratedDraftBundle",
    "ReviewFinding",
    "ReviewedDraftBundle",
    "ReviewerFeedback",
    "VisualReview",
    "VisualReviewFinding",
]
