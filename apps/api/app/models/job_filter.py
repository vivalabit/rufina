from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped
from app.models.job_search import ScreeningSeniority


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobFilterSettingsRecord(OwnerScoped, Base):
    __tablename__ = "job_filter_settings"

    owner_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class JobFilterSettings(BaseModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    enabled: bool = False
    allowed_seniority: list[ScreeningSeniority] = Field(
        default_factory=list,
        max_length=9,
        alias="allowedSeniority",
    )
    excluded_seniority: list[ScreeningSeniority] = Field(
        default_factory=list,
        max_length=9,
        alias="excludedSeniority",
    )
    target_technologies: list[str] = Field(
        default_factory=list,
        max_length=50,
        alias="targetTechnologies",
    )
    excluded_technologies: list[str] = Field(
        default_factory=list,
        max_length=50,
        alias="excludedTechnologies",
    )

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )

    @field_validator("allowed_seniority", "excluded_seniority")
    @classmethod
    def deduplicate_seniority(
        cls,
        value: list[ScreeningSeniority],
    ) -> list[ScreeningSeniority]:
        return list(dict.fromkeys(value))

    @field_validator(
        "target_technologies",
        "excluded_technologies",
        mode="before",
    )
    @classmethod
    def normalize_technologies(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        if len(value) > 50:
            raise ValueError("technology lists must contain at most 50 entries")
        if any(not isinstance(technology, str) for technology in value):
            return value

        normalized: list[str] = []
        seen: set[str] = set()
        for technology in value:
            item = " ".join(technology.split())
            if not item:
                raise ValueError("technology entries must not be empty")
            if len(item) > 80:
                raise ValueError("technology entries must be at most 80 characters")
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def reject_conflicting_filters(self) -> "JobFilterSettings":
        seniority_overlap = set(self.allowed_seniority).intersection(self.excluded_seniority)
        if seniority_overlap:
            conflicting = ", ".join(sorted(seniority_overlap))
            raise ValueError(
                f"allowedSeniority and excludedSeniority must not overlap: {conflicting}"
            )

        excluded_technologies = {technology.casefold() for technology in self.excluded_technologies}
        technology_overlap = [
            technology
            for technology in self.target_technologies
            if technology.casefold() in excluded_technologies
        ]
        if technology_overlap:
            conflicting = ", ".join(technology_overlap)
            raise ValueError(
                f"targetTechnologies and excludedTechnologies must not overlap: {conflicting}"
            )
        return self


class JobFilterSettingsUpdateRequest(JobFilterSettings):
    pass


class JobFilterSettingsPayload(JobFilterSettings):
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
