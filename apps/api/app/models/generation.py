"""Public integration contract for vacancy-specific document generation.

The contract deliberately describes only the boundary between Tasko and a
document generator. Matching analysis, explanations, generation plans, and
algorithm-specific intermediate stages do not cross this boundary.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.models.documents import DocumentType

GenerationExecutionState = Literal["queued", "running", "completed", "failed"]
GenerationDocumentState = Literal["queued", "running", "completed", "failed"]
GenerationAvailabilityCode = Literal["available", "generator_unavailable"]

_PROHIBITED_CONTEXT_KEYS = {
    "analysis",
    "aimatch",
    "analysisplan",
    "applicationguide",
    "documentplan",
    "generationplan",
    "match",
    "matchanalysis",
    "matchexplanation",
    "matchreasons",
    "matchscore",
    "plan",
    "plans",
    "preparationanalysis",
    "reasons",
    "recommendations",
}


class GenerationContractModel(BaseModel):
    """Strict, immutable base for values exchanged with the generator."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


def _reject_internal_context(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            nested_path = f"{path}.{key}"
            if normalized_key in _PROHIBITED_CONTEXT_KEYS:
                raise ValueError(
                    f"Generation input must not contain matching analysis or plans ({nested_path})"
                )
            _reject_internal_context(nested, path=nested_path)
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_internal_context(nested, path=f"{path}[{index}]")


def without_internal_generation_context(value: Any) -> Any:
    """Copy source JSON while omitting match analysis and obsolete planning data."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized_key in _PROHIBITED_CONTEXT_KEYS:
                continue
            sanitized[str(key)] = without_internal_generation_context(nested)
        return sanitized
    if isinstance(value, list):
        return [without_internal_generation_context(nested) for nested in value]
    if isinstance(value, tuple):
        return [without_internal_generation_context(nested) for nested in value]
    return value


class GenerationApplicationSnapshot(GenerationContractModel):
    """The persisted application exactly as selected by the user."""

    id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    data: dict[str, JsonValue]

    @field_validator("data")
    @classmethod
    def exclude_matching_context(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _reject_internal_context(value, path="application.data")
        return value


class GenerationVacancySnapshot(GenerationContractModel):
    """A complete vacancy snapshot, independent from its match assessment."""

    id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    full_description: str = Field(min_length=1, max_length=200_000, alias="fullDescription")
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def exclude_matching_context(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _reject_internal_context(value, path="vacancy.data")
        return value


class GenerationMasterProfileVersion(GenerationContractModel):
    """One immutable, explicitly selected version of the master profile."""

    id: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)
    content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        alias="contentSha256",
    )
    data: dict[str, JsonValue]

    @field_validator("data")
    @classmethod
    def exclude_matching_context(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _reject_internal_context(value, path="masterProfileVersion.data")
        return value


class GenerationRequest(GenerationContractModel):
    """All authoritative inputs the document generator may use."""

    application: GenerationApplicationSnapshot
    vacancy: GenerationVacancySnapshot
    master_profile_version: GenerationMasterProfileVersion = Field(alias="masterProfileVersion")
    document_types: tuple[DocumentType, ...] = Field(
        min_length=1,
        max_length=2,
        alias="documentTypes",
    )
    language: str = Field(min_length=1, max_length=40)
    formatting_parameters: dict[str, JsonValue] = Field(alias="formattingParameters")
    user_preferences: str = Field(max_length=10_000, alias="userPreferences")

    @field_validator("document_types")
    @classmethod
    def require_unique_document_types(
        cls,
        value: tuple[DocumentType, ...],
    ) -> tuple[DocumentType, ...]:
        if len(value) != len(set(value)):
            raise ValueError("documentTypes must not contain duplicates")
        return value


class GenerationStartRequest(GenerationContractModel):
    """User-approved options accepted by the application generation endpoint."""

    document_types: tuple[DocumentType, ...] = Field(
        min_length=1,
        max_length=2,
        alias="documentTypes",
    )
    language: str = Field(min_length=1, max_length=40)
    formatting_parameters: dict[str, JsonValue] = Field(alias="formattingParameters")
    user_preferences: str = Field(max_length=10_000, alias="userPreferences")
    master_profile_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        alias="masterProfileId",
    )
    master_profile_version: int | None = Field(
        default=None,
        ge=1,
        alias="masterProfileVersion",
    )

    @field_validator("document_types")
    @classmethod
    def require_unique_document_types(
        cls,
        value: tuple[DocumentType, ...],
    ) -> tuple[DocumentType, ...]:
        if len(value) != len(set(value)):
            raise ValueError("documentTypes must not contain duplicates")
        return value


class GenerationError(GenerationContractModel):
    """Stable machine code plus a message suitable for displaying to a user."""

    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    message: str = Field(min_length=1, max_length=1_000)
    retryable: bool = False


class GenerationAvailability(GenerationContractModel):
    """Whether the configured adapter can accept a new generation request."""

    available: bool
    code: GenerationAvailabilityCode
    message: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_availability(self) -> GenerationAvailability:
        if self.available != (self.code == "available"):
            raise ValueError("Generation availability code does not match available")
        return self


class GeneratedFile(GenerationContractModel):
    """A generated artifact exposed through application-owned file storage."""

    file_name: str = Field(min_length=1, max_length=240, alias="fileName")
    content_type: str = Field(min_length=1, max_length=160, alias="contentType")
    download_url: str = Field(min_length=1, max_length=2_000, alias="downloadUrl")


class GenerationDocumentResult(GenerationContractModel):
    """Current or final outcome for one requested document type."""

    document_type: DocumentType = Field(alias="documentType")
    state: GenerationDocumentState
    files: tuple[GeneratedFile, ...] = ()
    error: GenerationError | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> GenerationDocumentResult:
        if self.state == "completed" and not self.files:
            raise ValueError("A completed document result must contain at least one file")
        if self.state == "failed" and self.error is None:
            raise ValueError("A failed document result must contain an error")
        if self.state in {"queued", "running"} and (self.files or self.error is not None):
            raise ValueError("An unfinished document result cannot contain files or an error")
        if self.state == "completed" and self.error is not None:
            raise ValueError("A completed document result cannot contain an error")
        return self


class GenerationResult(GenerationContractModel):
    """Observable state returned by any document generator implementation.

    ``completed`` means the run has stopped; individual document results still
    carry success or failure so partial completion remains representable.
    """

    execution_id: str = Field(min_length=1, max_length=160, alias="executionId")
    state: GenerationExecutionState
    documents: tuple[GenerationDocumentResult, ...] = Field(min_length=1, max_length=2)
    error: GenerationError | None = None

    @model_validator(mode="after")
    def validate_execution_state(self) -> GenerationResult:
        document_types = [document.document_type for document in self.documents]
        if len(document_types) != len(set(document_types)):
            raise ValueError("documents must contain one result per document type")
        if self.state == "failed" and self.error is None:
            raise ValueError("A failed generation result must contain an error")
        if self.state in {"queued", "running"} and self.error is not None:
            raise ValueError("An unfinished generation result cannot contain a terminal error")
        if self.state in {"completed", "failed"} and any(
            document.state in {"queued", "running"} for document in self.documents
        ):
            raise ValueError("A finished generation result cannot contain unfinished documents")
        return self


__all__ = [
    "GeneratedFile",
    "GenerationApplicationSnapshot",
    "GenerationAvailability",
    "GenerationAvailabilityCode",
    "GenerationDocumentResult",
    "GenerationDocumentState",
    "GenerationError",
    "GenerationExecutionState",
    "GenerationMasterProfileVersion",
    "GenerationRequest",
    "GenerationResult",
    "GenerationStartRequest",
    "GenerationVacancySnapshot",
    "without_internal_generation_context",
]
