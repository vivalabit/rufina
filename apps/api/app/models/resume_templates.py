from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.core.database import Base, OwnerScoped
from app.services.resume_template_registry import ResumeTemplateId


DesignTokenName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$",
    ),
]
HexColor = Annotated[
    str,
    StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$"),
]
ContentSha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
SidebarSection = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResumeTemplatePageMargins(BaseModel):
    """Page margins in millimetres."""

    top: float = Field(ge=5, le=40)
    right: float = Field(ge=5, le=40)
    bottom: float = Field(ge=5, le=40)
    left: float = Field(ge=5, le=40)

    model_config = ConfigDict(extra="forbid")


class ResumeTemplateDesignTokens(BaseModel):
    """The complete, safe set of user-configurable resume design tokens."""

    accent_color: HexColor = Field(alias="accentColor")
    font_family: DesignTokenName = Field(alias="fontFamily")
    font_scale: float = Field(ge=0.75, le=1.5, alias="fontScale")
    density: Literal["compact", "standard", "comfortable"]
    page_margins: ResumeTemplatePageMargins = Field(alias="pageMargins")
    heading_style: DesignTokenName = Field(alias="headingStyle")
    skills_style: DesignTokenName = Field(alias="skillsStyle")
    sidebar_width: float = Field(ge=0, le=50, alias="sidebarWidth")
    sidebar_sections: list[SidebarSection] = Field(
        min_length=0,
        max_length=12,
        alias="sidebarSections",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("sidebar_sections")
    @classmethod
    def require_unique_sidebar_sections(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("sidebarSections must not contain duplicates")
        return value


class ValidatedResumeTemplateDesignJSON(TypeDecorator[dict[str, object]]):
    """JSON type that rejects unvalidated resume design data at persistence time."""

    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: object,
        dialect: Dialect,
    ) -> dict[str, object] | None:
        del dialect
        if value is None:
            return None
        design = ResumeTemplateDesignTokens.model_validate(value)
        return design.model_dump(mode="json")


class ResumeTemplateDefinitionRecord(OwnerScoped, Base):
    __tablename__ = "resume_template_definitions"
    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_resume_template_definitions_version_positive",
        ),
        Index(
            "ix_resume_template_definitions_owner_base",
            "owner_id",
            "base_template_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    base_template_id: Mapped[str] = mapped_column(String(80), nullable=False)
    design_json: Mapped[dict[str, object]] = mapped_column(
        ValidatedResumeTemplateDesignJSON(),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )


class ResumeTemplateDefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    base_template_id: ResumeTemplateId = Field(alias="baseTemplateId")
    design_json: ResumeTemplateDesignTokens = Field(alias="designJson")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class ResumeTemplateDefinitionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    base_template_id: ResumeTemplateId | None = Field(
        default=None,
        alias="baseTemplateId",
    )
    design_json: ResumeTemplateDesignTokens | None = Field(
        default=None,
        alias="designJson",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> ResumeTemplateDefinitionUpdateRequest:
        if self.name is None and self.base_template_id is None and self.design_json is None:
            raise ValueError("At least one template field must be provided")
        return self


class ResumeTemplateDefinitionDuplicateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class ResumeTemplatePreviewRequest(BaseModel):
    base_template_id: ResumeTemplateId = Field(alias="baseTemplateId")
    design_json: ResumeTemplateDesignTokens = Field(alias="designJson")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ResumeTemplateBackupPayload(BaseModel):
    """Portable template data that is safe to store outside the application."""

    format: Literal["rufina.resume-template"]
    schema_version: Literal[1] = Field(alias="schemaVersion")
    name: str = Field(min_length=1, max_length=240)
    base_template_id: ResumeTemplateId = Field(alias="baseTemplateId")
    design_json: ResumeTemplateDesignTokens = Field(alias="designJson")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class ResumeTemplateDefinitionResponse(BaseModel):
    id: str
    owner_id: str = Field(alias="ownerId")
    name: str
    base_template_id: ResumeTemplateId = Field(alias="baseTemplateId")
    design_json: ResumeTemplateDesignTokens = Field(alias="designJson")
    version: int = Field(ge=1)
    content_sha256: ContentSha256 = Field(alias="contentSha256")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ResumeTemplatePayload(BaseModel):
    id: str
    kind: Literal["bundled", "custom"]
    name: str
    description: str
    layout: Literal["single_column", "two_column"]
    columns: Literal[1, 2]
    base_template_id: ResumeTemplateId = Field(alias="baseTemplateId")
    design_json: ResumeTemplateDesignTokens | None = Field(
        default=None,
        alias="designJson",
    )
    version: int | None = Field(default=None, ge=1)
    content_sha256: ContentSha256 | None = Field(
        default=None,
        alias="contentSha256",
    )
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


__all__ = [
    "ResumeTemplateDefinitionCreateRequest",
    "ResumeTemplateDefinitionDuplicateRequest",
    "ResumeTemplateDefinitionRecord",
    "ResumeTemplateDefinitionResponse",
    "ResumeTemplateDefinitionUpdateRequest",
    "ResumeTemplateBackupPayload",
    "ResumeTemplateDesignTokens",
    "ResumeTemplatePageMargins",
    "ResumeTemplatePayload",
    "ResumeTemplatePreviewRequest",
]
