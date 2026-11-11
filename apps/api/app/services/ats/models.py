"""Contracts for ATS tailoring: the normalized vacancy target and the model draft."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

Seniority = Literal["intern", "junior", "mid", "senior", "lead", "unknown"]
PostingLanguage = Literal["de", "en", "fr", "it", "unknown"]
SkillImportance = Literal["required", "preferred"]
SkillSource = Literal["model", "dictionary"]
KnockoutKind = Literal[
    "work_permit", "language", "location", "degree", "experience", "certification", "other"
]
CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]

JOB_TARGET_SCHEMA_VERSION = 1


class StrictAtsModel(BaseModel):
    """Strict, immutable base for persisted ATS structures (same rules as StrictResumeModel)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        validate_default=True,
    )


class JobKnockout(StrictAtsModel):
    kind: KnockoutKind
    requirement: str = Field(min_length=1, max_length=300)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    cefr_level: CefrLevel | None = None
    years: int | None = Field(default=None, ge=1, le=40)


class JobSkill(StrictAtsModel):
    canonical_id: str | None = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    surface_form: str = Field(min_length=1, max_length=80)
    importance: SkillImportance
    frequency: int = Field(ge=1)
    min_years: int | None = Field(default=None, ge=1, le=30)
    source: SkillSource

    @property
    def key(self) -> str:
        return self.canonical_id or f"raw:{self.surface_form.casefold()}"


class JobTarget(StrictAtsModel):
    """What a vacancy asks for, normalized against the skill dictionary.

    `surface_form` is the exact spelling used in the posting; the planner puts that form
    into the resume. `canonical_id` is null for skills outside the dictionary.
    """

    schema_version: Literal[1] = JOB_TARGET_SCHEMA_VERSION
    title: str = Field(max_length=300)
    normalized_title: str = Field(max_length=300)
    seniority: Seniority
    language: PostingLanguage
    knockouts: tuple[JobKnockout, ...]
    responsibilities: tuple[str, ...]
    skills: tuple[JobSkill, ...]
    extractor_version: str = Field(min_length=1)
    dictionary_version: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = ""

    @model_validator(mode="after")
    def validate_unique_skills(self) -> JobTarget:
        keys = [skill.key for skill in self.skills]
        if len(keys) != len(set(keys)):
            raise ValueError("job target skills must be unique")
        return self

    @property
    def required_skills(self) -> tuple[JobSkill, ...]:
        return tuple(skill for skill in self.skills if skill.importance == "required")

    @property
    def preferred_skills(self) -> tuple[JobSkill, ...]:
        return tuple(skill for skill in self.skills if skill.importance == "preferred")

    @property
    def unmapped_skills(self) -> tuple[JobSkill, ...]:
        return tuple(skill for skill in self.skills if skill.canonical_id is None)


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


class DraftModel(BaseModel):
    """Lenient base for model output: normalization happens in code, not here."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class JobSkillDraft(DraftModel):
    surface_form: str
    importance: Annotated[SkillImportance, BeforeValidator(_lower)]
    min_years: int | None


class JobKnockoutDraft(DraftModel):
    kind: Annotated[KnockoutKind, BeforeValidator(_lower)]
    requirement: str
    language: str | None
    cefr_level: str | None
    years: int | None


class JobTargetDraft(DraftModel):
    """Structured-output contract for the vacancy parsing call.

    All fields are required and nullable instead of defaulted, as OpenAI strict schemas need.
    """

    title: str
    seniority: Annotated[Seniority, BeforeValidator(_lower)]
    language: Annotated[PostingLanguage, BeforeValidator(_lower)]
    knockouts: list[JobKnockoutDraft]
    responsibilities: list[str]
    skills: list[JobSkillDraft]
