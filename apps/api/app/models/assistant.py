from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


class AssistantAiMatchContext(BaseModel):
    reasons: list[str] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    application_guide: dict[str, Any] | None = Field(default=None, alias="applicationGuide")

    model_config = {"populate_by_name": True}


class AssistantJobContext(BaseModel):
    id: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=240)
    company: str = Field(default="", max_length=240)
    location: str = Field(default="", max_length=240)
    type: str = Field(default="", max_length=120)
    match: int = Field(default=0, ge=0, le=100)
    overview: str = Field(default="", max_length=12_000)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    requirements: list[str] = Field(default_factory=list, max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=80)
    ai_match: AssistantAiMatchContext | None = Field(default=None, alias="aiMatch")

    model_config = {"populate_by_name": True}


class AssistantApplicationContext(BaseModel):
    id: str = Field(default="", max_length=160)
    status: str = Field(default="", max_length=80)
    next_step: str = Field(default="", max_length=500, alias="nextStep")
    notes: str = Field(default="", max_length=12_000)
    generation_date: str = Field(default="", max_length=10, alias="generationDate")
    job: AssistantJobContext

    model_config = {"populate_by_name": True}


class AssistantSourceDocument(BaseModel):
    id: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=240)
    category: str = Field(default="", max_length=120)
    file_name: str = Field(min_length=1, max_length=240, alias="fileName")
    # A 10 MB binary upload expands to roughly 13.4 MB when encoded as a data URL.
    data_url: str = Field(min_length=1, max_length=15_000_000, alias="dataUrl")

    model_config = {"populate_by_name": True}


class AssistantCandidateConfirmation(BaseModel):
    question_id: str = Field(default="", max_length=160, alias="questionId")
    requirement: str = Field(default="", max_length=500)
    question: str = Field(default="", max_length=1_200)
    why: str = Field(default="", max_length=500)
    claim_if_confirmed: str = Field(
        default="",
        max_length=500,
        alias="claimIfConfirmed",
    )
    answer: str = Field(min_length=1, max_length=1_500)

    model_config = {"populate_by_name": True}


class AssistantGenerationContextReference(BaseModel):
    application_id: str = Field(min_length=1, max_length=160, alias="applicationId")
    template_id: str = Field(min_length=1, max_length=160, alias="templateId")
    document_type: Literal["cover_letter", "tailored_resume"] = Field(alias="documentType")
    target_language: Literal["English", "German"] | None = Field(
        default=None,
        alias="targetLanguage",
    )

    model_config = {"populate_by_name": True}


class AssistantChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=160, alias="threadId")
    message: str = Field(min_length=1, max_length=12_000)
    context_kind: Literal["profile", "job", "application"] = Field(alias="contextKind")
    context_id: str = Field(default="", max_length=160, alias="contextId")
    job: AssistantJobContext | None = None
    application: AssistantApplicationContext | None = None
    source_documents: list[AssistantSourceDocument] = Field(
        default_factory=list,
        max_length=3,
        alias="sourceDocuments",
    )
    candidate_confirmations: list[AssistantCandidateConfirmation] = Field(
        default_factory=list,
        max_length=20,
        alias="candidateConfirmations",
    )
    generation_context: AssistantGenerationContextReference | None = Field(
        default=None,
        alias="generationContext",
    )

    model_config = {"populate_by_name": True}


class AssistantStreamRequest(AssistantChatRequest):
    request_id: str = Field(min_length=1, max_length=160, alias="requestId")
    user_message_id: str = Field(default="", max_length=160, alias="userMessageId")
    assistant_message_id: str = Field(default="", max_length=160, alias="assistantMessageId")
    conversation_title: str = Field(default="", max_length=240, alias="conversationTitle")
    offset: int = Field(default=0, ge=0, le=1_000_000)


class AssistantChatResponse(BaseModel):
    message: str
    source: Literal["openclaw_codex", "openai_api", "local"] = "openclaw_codex"
    metadata: dict[str, Any] = Field(default_factory=dict)


AssistantActionType = Literal[
    "add_application_note",
    "update_application_next_step",
    "create_interview_event",
    "save_document",
    "update_profile_field",
]

ProfileActionField = Literal[
    "name",
    "current_role",
    "desired_role",
    "location",
    "work_format",
    "headline",
    "linkedin",
    "github",
    "portfolio",
    "personal_site",
    "experience",
    "skills",
    "education",
    "job_preferences",
    "dealbreakers",
    "additional_notes",
]


class AddApplicationNoteProposal(BaseModel):
    type: Literal["add_application_note"]
    note: str = Field(min_length=1, max_length=4_000)


class UpdateApplicationNextStepProposal(BaseModel):
    type: Literal["update_application_next_step"]
    next_step: str = Field(min_length=1, max_length=500, alias="nextStep")

    model_config = {"populate_by_name": True}


class CreateInterviewEventProposal(BaseModel):
    type: Literal["create_interview_event"]
    title: str = Field(min_length=1, max_length=240)
    starts_at: datetime = Field(alias="startsAt")
    duration_minutes: int = Field(default=45, ge=5, le=480, alias="durationMinutes")
    timezone: str = Field(default="UTC", min_length=1, max_length=120)
    location: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=4_000)

    model_config = {"populate_by_name": True}


class SaveDocumentProposal(BaseModel):
    type: Literal["save_document"]
    document_type: Literal["cover_letter", "tailored_resume"] = Field(alias="documentType")
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)

    model_config = {"populate_by_name": True}


class UpdateProfileFieldProposal(BaseModel):
    type: Literal["update_profile_field"]
    field: ProfileActionField
    value: str = Field(max_length=12_000)


class AssistantActionFieldPreview(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    before: str = Field(default="", max_length=12_000)
    after: str = Field(default="", max_length=200_000)


class AssistantActionPreview(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    type: AssistantActionType
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    context_kind: Literal["profile", "job", "application"] = Field(alias="contextKind")
    context_id: str = Field(default="", max_length=160, alias="contextId")
    fields: list[AssistantActionFieldPreview] = Field(default_factory=list, max_length=8)
    payload: dict[str, Any]
    status: Literal["preview", "applied"] = "preview"
    result_message: str = Field(default="", max_length=500, alias="resultMessage")

    model_config = {"populate_by_name": True}


class AssistantActionApplyRequest(BaseModel):
    action: AssistantActionPreview


class AssistantActionApplyResponse(BaseModel):
    action_id: str = Field(alias="actionId")
    type: AssistantActionType
    status: Literal["applied"] = "applied"
    message: str
    resource_kind: Literal["application", "event", "document", "profile"] = Field(
        alias="resourceKind"
    )
    resource: dict[str, Any]

    model_config = {"populate_by_name": True}


class AppliedAssistantActionRecord(OwnerScoped, Base):
    __tablename__ = "applied_assistant_actions"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
