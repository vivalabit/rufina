from copy import deepcopy
from datetime import UTC, datetime, time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, OwnerScoped
from app.core.vacancy_sources import (
    AGGREGATOR_SOURCE_IDS,
    SUPPORTED_VACANCY_SOURCE_IDS,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobSearchConfigRecord(OwnerScoped, Base):
    __tablename__ = "job_search_configs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
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
    schedules: Mapped[list["JobSearchScheduleRecord"]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
    )
    source_configs: Mapped[list["JobSourceConfigRecord"]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
    )
    presets: Mapped[list["JobSearchPresetRecord"]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
    )


class JobSourceConfigRecord(OwnerScoped, Base):
    __tablename__ = "job_source_configs"
    __table_args__ = (
        Index(
            "ix_job_source_configs_config_source",
            "config_id",
            "source",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    config_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_search_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
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
    config: Mapped[JobSearchConfigRecord] = relationship(
        back_populates="source_configs",
    )


class JobSearchPresetRecord(OwnerScoped, Base):
    __tablename__ = "job_search_presets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    config_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_search_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_config_ids: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
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
    config: Mapped[JobSearchConfigRecord] = relationship(back_populates="presets")


class JobSearchScheduleRecord(OwnerScoped, Base):
    __tablename__ = "job_search_schedules"
    __table_args__ = (
        Index(
            "ix_job_search_schedules_due",
            "enabled",
            "next_run_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    config_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_search_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_config_ids: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    preset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("job_search_presets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    weekdays: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    local_time: Mapped[time] = mapped_column(Time(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_analysis_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    )
    config: Mapped[JobSearchConfigRecord] = relationship(back_populates="schedules")
    runs: Mapped[list["JobSearchRunRecord"]] = relationship(
        back_populates="schedule",
        passive_deletes=True,
    )


class JobSearchRunRecord(OwnerScoped, Base):
    __tablename__ = "job_search_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('manual', 'automatic')",
            name="ck_job_search_runs_run_type",
        ),
        Index(
            "uq_job_search_runs_automatic_schedule_time",
            "schedule_id",
            "scheduled_for",
            unique=True,
            sqlite_where=text("run_type = 'automatic'"),
            postgresql_where=text("run_type = 'automatic'"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("job_search_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    jobs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_already_known: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_discovered_new: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_discovered_updated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_already_observed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_screened: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_passed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_rejected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_uncertain: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_analyzed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    screening_errors: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    jobs_screening_ai_calls: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    warning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_errors: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    schedule: Mapped[JobSearchScheduleRecord | None] = relationship(
        back_populates="runs",
    )


JobSearchFrequency = Literal["daily", "weekdays", "selected_days"]
JobSearchSource = str
ScreeningField = Literal[
    "title",
    "company",
    "location",
    "description",
    "employment_type",
    "employmentType",
    "seniority",
    "salary_min",
    "salaryMin",
    "salary_max",
    "salaryMax",
    "posted_at",
    "postedAt",
    "source",
]
ScreeningOperator = Literal[
    "equals",
    "not_equals",
    "notEquals",
    "contains",
    "not_contains",
    "notContains",
    "starts_with",
    "startsWith",
    "ends_with",
    "endsWith",
    "greater_than",
    "greaterThan",
    "greater_than_or_equal",
    "greaterThanOrEqual",
    "less_than",
    "lessThan",
    "less_than_or_equal",
    "lessThanOrEqual",
    "in",
    "not_in",
    "notIn",
    "matches",
]
ScreeningValue = str | int | float | bool | list[str]
ScreeningSeniority = Literal[
    "intern",
    "entry",
    "junior",
    "associate",
    "mid",
    "senior",
    "lead",
    "director",
    "executive",
]


class SearchFilters(BaseModel):
    keywords: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=160)
    remote: Literal["Any", "Remote only", "Hybrid", "On-site"] = "Any"
    experience_level: Literal[
        "Any",
        "Entry level",
        "Associate",
        "Mid-Senior level",
        "Director",
    ] = Field(default="Any", alias="experienceLevel")
    job_type: Literal[
        "Any",
        "Full-time",
        "Part-time",
        "Contract",
        "Internship",
    ] = Field(default="Any", alias="jobType")
    date_posted: Literal[
        "Any time",
        "Past 24 hours",
        "Past week",
        "Past month",
    ] = Field(default="Any time", alias="datePosted")
    results_limit: int = Field(default=100, ge=1, le=1000, alias="resultsLimit")
    country: str = Field(default="Any", max_length=80)
    deduplicate: bool = True

    search_name: str = Field(default="", max_length=160, alias="searchName")
    folder: str = Field(default="", max_length=120)

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
    }


class ScreeningRule(BaseModel):
    field: ScreeningField
    operator: ScreeningOperator
    value: ScreeningValue
    enabled: bool = True

    model_config = {
        "extra": "forbid",
        "strict": True,
    }


class ScreeningConfig(BaseModel):
    enabled: bool = False
    target_roles: list[str] = Field(
        default_factory=list,
        max_length=50,
        alias="targetRoles",
    )
    excluded_roles: list[str] = Field(
        default_factory=list,
        max_length=50,
        alias="excludedRoles",
    )
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
    hard_rules: list[ScreeningRule] = Field(
        default_factory=list,
        max_length=100,
        alias="hardRules",
    )

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
        "strict": True,
    }

    @field_validator("target_roles", "excluded_roles")
    @classmethod
    def normalize_roles(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(role.strip() for role in value))
        if any(not role for role in normalized):
            raise ValueError("role lists must not contain empty roles")
        if any(len(role) > 160 for role in normalized):
            raise ValueError("role entries must be at most 160 characters")
        return normalized

    @field_validator("allowed_seniority", "excluded_seniority")
    @classmethod
    def deduplicate_seniority(
        cls,
        value: list[ScreeningSeniority],
    ) -> list[ScreeningSeniority]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def reject_conflicting_seniority(self) -> "ScreeningConfig":
        overlap = set(self.allowed_seniority).intersection(self.excluded_seniority)
        if overlap:
            conflicting = ", ".join(sorted(overlap))
            raise ValueError(
                "allowedSeniority and excludedSeniority must not overlap: "
                f"{conflicting}"
            )
        return self


class JobSearchConfigV2(BaseModel):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    search: SearchFilters
    screening: ScreeningConfig = Field(default_factory=ScreeningConfig)

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
        "strict": True,
    }


LEGACY_SEARCH_ALIASES = {
    "query": "keywords",
    "experienceLevel": "experience_level",
    "jobType": "job_type",
    "datePosted": "date_posted",
    "resultsLimit": "results_limit",
    "searchName": "search_name",
}
VERSIONED_CONFIG_FIELDS = {"schemaVersion", "schema_version", "search", "screening"}


def normalize_job_search_config(config: dict[str, Any]) -> JobSearchConfigV2:
    if VERSIONED_CONFIG_FIELDS.intersection(config):
        projected = project_known_model_fields(config, JobSearchConfigV2)
        search = projected.get("search")
        if isinstance(search, dict):
            projected["search"] = project_known_model_fields(
                search,
                SearchFilters,
            )
        screening = projected.get("screening")
        if isinstance(screening, dict):
            projected_screening = project_known_model_fields(
                screening,
                ScreeningConfig,
            )
            hard_rules = projected_screening.get("hardRules")
            if isinstance(hard_rules, list):
                projected_screening["hardRules"] = [
                    project_known_model_fields(rule, ScreeningRule)
                    if isinstance(rule, dict)
                    else rule
                    for rule in hard_rules
                ]
            projected["screening"] = projected_screening
        return JobSearchConfigV2.model_validate(projected)

    search_field_names = set(SearchFilters.model_fields)
    normalized_search = {
        normalized_key: value
        for key, value in config.items()
        if (normalized_key := LEGACY_SEARCH_ALIASES.get(key, key)) in search_field_names
    }
    return JobSearchConfigV2(
        schema_version=2,
        search=SearchFilters.model_validate(normalized_search),
    )


def validate_versioned_job_search_config(config: dict[str, Any]) -> dict[str, Any]:
    if not VERSIONED_CONFIG_FIELDS.intersection(config):
        return config
    normalized = normalize_job_search_config(config).model_dump(
        by_alias=True,
        exclude_none=True,
    )
    preserved = deepcopy(config)
    preserved["schemaVersion"] = normalized["schemaVersion"]
    preserved["search"] = merge_preserving_unknown(
        config.get("search"),
        normalized["search"],
    )
    preserved["screening"] = merge_screening_preserving_unknown(
        config.get("screening"),
        normalized["screening"],
    )
    return preserved


def project_known_model_fields(
    value: dict[str, Any],
    model: type[BaseModel],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        alias = field.alias or name
        if alias in value:
            projected[alias] = value[alias]
        elif name in value:
            projected[name] = value[name]
    return projected


def merge_preserving_unknown(
    original: object,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    return {
        **(deepcopy(original) if isinstance(original, dict) else {}),
        **normalized,
    }


def merge_screening_preserving_unknown(
    original: object,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    merged = merge_preserving_unknown(original, normalized)
    original_rules = (
        original.get("hardRules")
        if isinstance(original, dict)
        else None
    )
    normalized_rules = normalized.get("hardRules")
    if isinstance(normalized_rules, list):
        merged["hardRules"] = [
            merge_preserving_unknown(
                original_rules[index]
                if isinstance(original_rules, list)
                and index < len(original_rules)
                else None,
                rule,
            )
            if isinstance(rule, dict)
            else rule
            for index, rule in enumerate(normalized_rules)
        ]
    return merged


class JobSearchConfigCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    filters: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_versioned_job_search_config(value)


class JobSearchConfigUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    filters: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return validate_versioned_job_search_config(value)


class JobSearchConfigPayload(BaseModel):
    id: str
    name: str
    filters: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return as_utc(value)


class JobSourceConfigCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    config_id: str = Field(min_length=1, max_length=36, alias="configId")
    source: JobSearchSource
    filters: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: JobSearchSource) -> JobSearchSource:
        return validate_aggregator_source(value)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_source_filters(value)


class JobSourceConfigUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    config_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="configId",
    )
    source: JobSearchSource | None = None
    filters: dict[str, Any] | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return (
            normalize_required_text(value, field_name="name")
            if value is not None
            else None
        )

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: JobSearchSource | None) -> JobSearchSource | None:
        return validate_aggregator_source(value) if value is not None else None

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return normalize_source_filters(value) if value is not None else None


class JobSourceConfigPayload(BaseModel):
    id: str
    name: str
    config_id: str = Field(alias="configId")
    source: JobSearchSource
    filters: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return as_utc(value)


class JobSearchPresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    config_id: str = Field(min_length=1, max_length=36, alias="configId")
    sources: list[JobSearchSource] = Field(min_length=1, max_length=500)
    source_config_ids: dict[str, str] = Field(
        default_factory=dict,
        alias="sourceConfigIds",
    )

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("sources")
    @classmethod
    def normalize_sources(cls, value: list[JobSearchSource]) -> list[JobSearchSource]:
        return validate_job_search_sources(value)

    @field_validator("source_config_ids")
    @classmethod
    def normalize_source_configs(cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_source_config_ids(value)


class JobSearchPresetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    config_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="configId",
    )
    sources: list[JobSearchSource] | None = Field(
        default=None,
        min_length=1,
        max_length=500,
    )
    source_config_ids: dict[str, str] | None = Field(
        default=None,
        alias="sourceConfigIds",
    )

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return (
            normalize_required_text(value, field_name="name")
            if value is not None
            else None
        )

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls,
        value: list[JobSearchSource] | None,
    ) -> list[JobSearchSource] | None:
        return validate_job_search_sources(value) if value is not None else None

    @field_validator("source_config_ids")
    @classmethod
    def normalize_source_configs(
        cls,
        value: dict[str, str] | None,
    ) -> dict[str, str] | None:
        return normalize_source_config_ids(value) if value is not None else None


class JobSearchPresetPayload(BaseModel):
    id: str
    name: str
    config_id: str = Field(alias="configId")
    sources: list[JobSearchSource]
    source_config_ids: dict[str, str] = Field(alias="sourceConfigIds")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return as_utc(value)


class JobSearchRescreenRequest(BaseModel):
    dry_run: bool = Field(default=True, alias="dryRun")
    confirm: bool = False
    use_selected_config_as_fallback: bool = Field(
        default=False,
        alias="useSelectedConfigAsFallback",
    )
    confirmation_token: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        alias="confirmationToken",
    )

    model_config = {"extra": "forbid", "populate_by_name": True}


class JobSearchRescreenConfigGroupPayload(BaseModel):
    config_id: str = Field(alias="configId")
    config_hash: str = Field(alias="configHash")
    used_as_fallback: bool = Field(alias="usedAsFallback")
    fallback_jobs: int = Field(alias="fallbackJobs", ge=0)
    jobs: int = Field(ge=0)
    jobs_screened: int = Field(alias="jobsScreened", ge=0)
    jobs_passed: int = Field(alias="jobsPassed", ge=0)
    jobs_rejected: int = Field(alias="jobsRejected", ge=0)
    jobs_uncertain: int = Field(alias="jobsUncertain", ge=0)
    screening_errors: int = Field(alias="screeningErrors", ge=0)

    model_config = {"populate_by_name": True}


class JobSearchRescreenPayload(BaseModel):
    config_id: str = Field(alias="configId")
    config_hash: str = Field(alias="configHash")
    dry_run: bool = Field(alias="dryRun")
    applied: bool
    eligible_jobs: int = Field(alias="eligibleJobs", ge=0)
    jobs_screened: int = Field(alias="jobsScreened", ge=0)
    jobs_passed: int = Field(alias="jobsPassed", ge=0)
    jobs_rejected: int = Field(alias="jobsRejected", ge=0)
    jobs_uncertain: int = Field(alias="jobsUncertain", ge=0)
    screening_errors: int = Field(alias="screeningErrors", ge=0)
    jobs_skipped: int = Field(alias="jobsSkipped", ge=0)
    jobs_using_fallback: int = Field(alias="jobsUsingFallback", ge=0)
    skipped_reasons: dict[str, int] = Field(
        default_factory=dict,
        alias="skippedReasons",
    )
    config_groups: list[JobSearchRescreenConfigGroupPayload] = Field(
        default_factory=list,
        alias="configGroups",
    )
    jobs_to_hide: int = Field(alias="jobsToHide", ge=0)
    jobs_to_restore: int = Field(alias="jobsToRestore", ge=0)
    jobs_hidden: int = Field(alias="jobsHidden", ge=0)
    jobs_restored: int = Field(alias="jobsRestored", ge=0)
    confirmation_token: str = Field(
        min_length=64,
        max_length=64,
        alias="confirmationToken",
    )
    warning: str | None = Field(default=None, max_length=500)

    model_config = {"populate_by_name": True}


class JobSearchManualRunRequest(BaseModel):
    preset_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="presetId",
    )
    config_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="configId",
    )
    config: JobSearchConfigCreateRequest | None = None
    sources: list[JobSearchSource] = Field(default_factory=list, max_length=500)
    source_config_ids: dict[str, str] = Field(
        default_factory=dict,
        alias="sourceConfigIds",
    )
    ai_analysis_enabled: bool = Field(default=True, alias="aiAnalysisEnabled")

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls,
        value: list[JobSearchSource],
    ) -> list[JobSearchSource]:
        return validate_job_search_sources(value)

    @field_validator("source_config_ids")
    @classmethod
    def normalize_source_configs(cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_source_config_ids(value)

    @model_validator(mode="after")
    def require_one_config_source(self) -> "JobSearchManualRunRequest":
        if self.preset_id:
            if self.config_id or self.config or self.sources or self.source_config_ids:
                raise ValueError(
                    "presetId cannot be combined with configId, config, sources, "
                    "or sourceConfigIds"
                )
            return self
        if bool(self.config_id) == bool(self.config):
            raise ValueError("provide presetId or exactly one of configId or config")
        if not self.sources:
            raise ValueError("select at least one source")
        return self


class JobSearchScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    preset_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="presetId",
    )
    config_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="configId",
    )
    sources: list[JobSearchSource] = Field(default_factory=list, max_length=500)
    source_config_ids: dict[str, str] = Field(
        default_factory=dict,
        alias="sourceConfigIds",
    )
    frequency: JobSearchFrequency
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    local_time: time = Field(alias="localTime")
    timezone: str = Field(min_length=1, max_length=64)
    ai_analysis_enabled: bool = Field(default=False, alias="aiAnalysisEnabled")
    enabled: bool = True

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name", "timezone")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls,
        value: list[JobSearchSource],
    ) -> list[JobSearchSource]:
        return validate_job_search_sources(value)

    @field_validator("source_config_ids")
    @classmethod
    def normalize_source_configs(cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_source_config_ids(value)

    @model_validator(mode="after")
    def require_preset_or_config(self) -> "JobSearchScheduleCreateRequest":
        if self.preset_id:
            if self.config_id or self.sources or self.source_config_ids:
                raise ValueError(
                    "presetId cannot be combined with configId, sources, or "
                    "sourceConfigIds"
                )
            return self
        if not self.config_id or not self.sources:
            raise ValueError("provide presetId or configId with at least one source")
        return self


class JobSearchScheduleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    config_id: str | None = Field(default=None, min_length=1, max_length=36, alias="configId")
    preset_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=36,
        alias="presetId",
    )
    sources: list[JobSearchSource] | None = Field(default=None, min_length=1, max_length=500)
    source_config_ids: dict[str, str] | None = Field(
        default=None,
        alias="sourceConfigIds",
    )
    frequency: JobSearchFrequency | None = None
    weekdays: list[int] | None = Field(default=None, max_length=7)
    local_time: time | None = Field(default=None, alias="localTime")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    ai_analysis_enabled: bool | None = Field(default=None, alias="aiAnalysisEnabled")
    enabled: bool | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("sources")
    @classmethod
    def normalize_sources(
        cls,
        value: list[JobSearchSource] | None,
    ) -> list[JobSearchSource] | None:
        return validate_job_search_sources(value) if value is not None else None

    @field_validator("source_config_ids")
    @classmethod
    def normalize_source_configs(
        cls,
        value: dict[str, str] | None,
    ) -> dict[str, str] | None:
        return normalize_source_config_ids(value) if value is not None else None


class JobSearchSchedulePayload(BaseModel):
    id: str
    name: str
    config_id: str = Field(alias="configId")
    preset_id: str | None = Field(alias="presetId")
    sources: list[JobSearchSource]
    source_config_ids: dict[str, str] = Field(alias="sourceConfigIds")
    frequency: JobSearchFrequency
    weekdays: list[int]
    local_time: time = Field(alias="localTime")
    timezone: str
    ai_analysis_enabled: bool = Field(alias="aiAnalysisEnabled")
    enabled: bool
    next_run_at: datetime | None = Field(alias="nextRunAt")
    last_run_at: datetime | None = Field(alias="lastRunAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator(
        "next_run_at",
        "last_run_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


class JobSearchRunPayload(BaseModel):
    id: str
    schedule_id: str | None = Field(alias="scheduleId")
    run_type: Literal["manual", "automatic"] = Field(alias="runType")
    scheduled_for: datetime | None = Field(alias="scheduledFor")
    config_snapshot: dict[str, Any] = Field(alias="configSnapshot")
    sources: list[JobSearchSource]
    status: str
    jobs_found: int = Field(alias="jobsFound", ge=0)
    jobs_already_known: int = Field(alias="jobsAlreadyKnown", ge=0)
    jobs_discovered_new: int = Field(alias="jobsDiscoveredNew", ge=0)
    jobs_discovered_updated: int = Field(alias="jobsDiscoveredUpdated", ge=0)
    jobs_already_observed: int = Field(alias="jobsAlreadyObserved", ge=0)
    jobs_screened: int = Field(alias="jobsScreened", ge=0)
    jobs_passed: int = Field(alias="jobsPassed", ge=0)
    jobs_rejected: int = Field(alias="jobsRejected", ge=0)
    jobs_uncertain: int = Field(alias="jobsUncertain", ge=0)
    jobs_added: int = Field(alias="jobsAdded", ge=0)
    jobs_analyzed: int = Field(alias="jobsAnalyzed", ge=0)
    screening_errors: int = Field(alias="screeningErrors", ge=0)
    jobs_screening_ai_calls: int = Field(alias="jobsScreeningAiCalls", ge=0)
    source_errors: dict[str, str] = Field(alias="sourceErrors")
    started_at: datetime = Field(alias="startedAt")
    completed_at: datetime | None = Field(alias="completedAt")
    warning: str | None = Field(default=None, max_length=500)

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator(
        "scheduled_for",
        "started_at",
        "completed_at",
        mode="before",
    )
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_source_ids(value: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(source.strip() for source in value))
    if any(not source for source in normalized):
        raise ValueError("vacancy sources must not be empty")
    return normalized


def validate_job_search_sources(value: list[str]) -> list[str]:
    normalized = normalize_source_ids(value)
    unsupported = [
        source for source in normalized if source not in SUPPORTED_VACANCY_SOURCE_IDS
    ]
    if unsupported:
        raise ValueError(f"Unsupported vacancy source: {unsupported[0]}")
    return normalized


def validate_aggregator_source(value: str) -> str:
    normalized = value.strip()
    if normalized not in AGGREGATOR_SOURCE_IDS:
        raise ValueError(f"Source configs are not supported for: {normalized}")
    return normalized


def normalize_source_filters(value: dict[str, Any]) -> dict[str, Any]:
    return SearchFilters.model_validate(value).model_dump(
        by_alias=True,
        exclude_none=True,
    )


def normalize_source_config_ids(value: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for source, config_id in value.items():
        normalized_source = validate_aggregator_source(source)
        normalized_id = config_id.strip()
        if not normalized_id:
            raise ValueError("source config ids must not be empty")
        if len(normalized_id) > 36:
            raise ValueError("source config ids must be at most 36 characters")
        normalized[normalized_source] = normalized_id
    return normalized


def normalize_required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized
