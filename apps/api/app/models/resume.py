from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


MAX_TEXT_LENGTH = 20_000
MAX_ITEMS_PER_SECTION = 100

CanonicalId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
ResumeId = CanonicalId
ResumeItemId = CanonicalId
ExperienceId = CanonicalId
EvidenceId = CanonicalId
JobId = CanonicalId
StrictText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_LENGTH),
]
OptionalText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_TEXT_LENGTH),
]

ResumeSectionName = Literal[
    "summary",
    "experience",
    "skills",
    "education",
    "projects",
    "certifications",
    "languages",
    "additional",
]
EvidenceKind = Literal[
    "source",
    "profile",
    "confirmation",
    "vacancy",
    "generation",
]
EvidenceClaimType = Literal[
    "employer",
    "title",
    "period",
    "technology",
    "achievement",
]


class StrictResumeModel(BaseModel):
    """Shared contract for persisted and AI-produced resume structures."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        validate_default=True,
    )


class ResumeEvidence(StrictResumeModel):
    """An authoritative fact that may support one or more resume statements."""

    id: EvidenceId
    type: EvidenceKind
    text: StrictText
    claim_type: EvidenceClaimType | None = Field(default=None, alias="claimType")
    experience_id: ExperienceId | None = Field(default=None, alias="experienceId")
    source_id: CanonicalId | None = Field(default=None, alias="sourceId")

    @model_validator(mode="after")
    def validate_evidence_identity(self) -> ResumeEvidence:
        if not self.id.startswith(f"{self.type}:"):
            raise ValueError("evidence ID must start with its type and a colon")
        has_claim_metadata = self.claim_type is not None or self.experience_id is not None
        if has_claim_metadata and (
            self.type != "profile"
            or self.claim_type is None
            or self.experience_id is None
        ):
            raise ValueError(
                "claimType and experienceId must be provided together for profile evidence"
            )
        return self


class EvidenceBackedText(StrictResumeModel):
    text: StrictText
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> EvidenceBackedText:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class ResumeBullet(EvidenceBackedText):
    id: ResumeItemId


class ResumeBasics(StrictResumeModel):
    full_name: StrictText = Field(alias="fullName", max_length=200)
    headline: OptionalText = Field(default="", max_length=300)
    email: OptionalText = Field(default="", max_length=320)
    phone: OptionalText = Field(default="", max_length=80)
    location: OptionalText = Field(default="", max_length=240)
    linkedin: OptionalText = Field(default="", max_length=500)
    github: OptionalText = Field(default="", max_length=500)
    portfolio: OptionalText = Field(default="", max_length=500)


class MasterExperience(StrictResumeModel):
    id: ExperienceId
    company: StrictText = Field(max_length=300)
    title: StrictText = Field(max_length=300)
    employment_type: OptionalText = Field(
        default="",
        alias="employmentType",
        max_length=120,
    )
    location: OptionalText = Field(default="", max_length=240)
    start_date: StrictText = Field(alias="startDate", max_length=40)
    end_date: OptionalText = Field(default="", alias="endDate", max_length=40)
    is_current: bool = Field(default=False, alias="isCurrent")
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def validate_experience(self) -> MasterExperience:
        if self.is_current and self.end_date:
            raise ValueError("endDate must be empty when isCurrent is true")
        if not self.is_current and not self.end_date:
            raise ValueError("endDate is required when isCurrent is false")
        _require_unique((bullet.id for bullet in self.bullets), "experience bullet IDs")
        return self


class MasterSkill(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=160)
    category: OptionalText = Field(default="", max_length=160)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterSkill:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class MasterEducation(StrictResumeModel):
    id: ResumeItemId
    institution: StrictText = Field(max_length=300)
    credential: StrictText = Field(max_length=300)
    field_of_study: OptionalText = Field(
        default="",
        alias="fieldOfStudy",
        max_length=300,
    )
    location: OptionalText = Field(default="", max_length=240)
    start_date: OptionalText = Field(default="", alias="startDate", max_length=40)
    end_date: OptionalText = Field(default="", alias="endDate", max_length=40)
    details: list[ResumeBullet] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )

    @model_validator(mode="after")
    def reject_duplicate_detail_ids(self) -> MasterEducation:
        _require_unique((detail.id for detail in self.details), "education detail IDs")
        return self


class MasterProject(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=300)
    role: OptionalText = Field(default="", max_length=300)
    url: OptionalText = Field(default="", max_length=500)
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def reject_duplicate_bullet_ids(self) -> MasterProject:
        _require_unique((bullet.id for bullet in self.bullets), "project bullet IDs")
        return self


class MasterCertification(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=300)
    issuer: StrictText = Field(max_length=300)
    issued_on: OptionalText = Field(default="", alias="issuedOn", max_length=40)
    expires_on: OptionalText = Field(default="", alias="expiresOn", max_length=40)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterCertification:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class MasterLanguage(StrictResumeModel):
    id: ResumeItemId
    name: StrictText = Field(max_length=120)
    proficiency: StrictText = Field(max_length=120)
    evidence_ids: list[EvidenceId] = Field(
        alias="evidenceIds",
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def reject_duplicate_evidence_ids(self) -> MasterLanguage:
        _require_unique(self.evidence_ids, "evidenceIds")
        return self


class AdditionalResumeSection(StrictResumeModel):
    id: ResumeItemId
    title: StrictText = Field(max_length=200)
    items: list[ResumeBullet] = Field(min_length=1, max_length=MAX_ITEMS_PER_SECTION)

    @model_validator(mode="after")
    def reject_duplicate_item_ids(self) -> AdditionalResumeSection:
        _require_unique((item.id for item in self.items), "additional section item IDs")
        return self


class MasterResume(StrictResumeModel):
    """Canonical, vacancy-independent resume and its evidence catalog."""

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    id: ResumeId
    language: StrictText = Field(max_length=40)
    basics: ResumeBasics
    summary: EvidenceBackedText | None = None
    experiences: list[MasterExperience] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    skills: list[MasterSkill] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    education: list[MasterEducation] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    projects: list[MasterProject] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    certifications: list[MasterCertification] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    languages: list[MasterLanguage] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    additional_sections: list[AdditionalResumeSection] = Field(
        default_factory=list,
        alias="additionalSections",
        max_length=MAX_ITEMS_PER_SECTION,
    )
    evidence: list[ResumeEvidence] = Field(max_length=2_000)
    section_order: list[ResumeSectionName] = Field(alias="sectionOrder", max_length=8)

    @model_validator(mode="after")
    def validate_canonical_resume(self) -> MasterResume:
        _validate_resume_graph(self)
        return self


class RewrittenExperience(StrictResumeModel):
    """One vacancy-specific rewrite linked to a canonical experience."""

    id: ResumeItemId
    master_experience_id: ExperienceId = Field(alias="masterExperienceId")
    company: StrictText = Field(max_length=300)
    title: StrictText = Field(max_length=300)
    location: OptionalText = Field(default="", max_length=240)
    period: StrictText = Field(max_length=100)
    bullets: list[ResumeBullet] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def reject_duplicate_bullet_ids(self) -> RewrittenExperience:
        _require_unique((bullet.id for bullet in self.bullets), "rewritten bullet IDs")
        return self


class ExperienceRewrite(StrictResumeModel):
    """Complete experience-rewrite result for one target vacancy."""

    master_resume_id: ResumeId = Field(alias="masterResumeId")
    target_job_id: JobId = Field(alias="targetJobId")
    experiences: list[RewrittenExperience] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_SECTION,
    )

    @model_validator(mode="after")
    def validate_rewrites(self) -> ExperienceRewrite:
        _require_unique((item.id for item in self.experiences), "rewrite IDs")
        _require_unique(
            (item.master_experience_id for item in self.experiences),
            "masterExperienceIds",
        )
        _require_unique(
            (bullet.id for item in self.experiences for bullet in item.bullets),
            "rewritten bullet IDs",
        )
        return self


class FinalResume(StrictResumeModel):
    """Self-contained tailored resume ready for deterministic rendering."""

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    id: ResumeId
    master_resume_id: ResumeId = Field(alias="masterResumeId")
    target_job_id: JobId = Field(alias="targetJobId")
    language: StrictText = Field(max_length=40)
    basics: ResumeBasics
    summary: EvidenceBackedText | None = None
    experiences: list[RewrittenExperience] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    skills: list[MasterSkill] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    education: list[MasterEducation] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    projects: list[MasterProject] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    certifications: list[MasterCertification] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    languages: list[MasterLanguage] = Field(
        default_factory=list,
        max_length=MAX_ITEMS_PER_SECTION,
    )
    additional_sections: list[AdditionalResumeSection] = Field(
        default_factory=list,
        alias="additionalSections",
        max_length=MAX_ITEMS_PER_SECTION,
    )
    evidence: list[ResumeEvidence] = Field(min_length=1, max_length=2_000)
    section_order: list[ResumeSectionName] = Field(
        alias="sectionOrder",
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_final_resume(self) -> FinalResume:
        _validate_resume_graph(self)
        _require_unique(
            (item.master_experience_id for item in self.experiences),
            "masterExperienceIds",
        )
        return self


def _require_unique(values: object, label: str) -> None:
    materialized = list(values)  # type: ignore[arg-type]
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} must not contain duplicates")


def _present_sections(resume: MasterResume | FinalResume) -> set[ResumeSectionName]:
    present: set[ResumeSectionName] = set()
    if resume.summary is not None:
        present.add("summary")
    if resume.experiences:
        present.add("experience")
    if resume.skills:
        present.add("skills")
    if resume.education:
        present.add("education")
    if resume.projects:
        present.add("projects")
    if resume.certifications:
        present.add("certifications")
    if resume.languages:
        present.add("languages")
    if resume.additional_sections:
        present.add("additional")
    return present


def _all_item_ids(resume: MasterResume | FinalResume) -> list[ResumeItemId]:
    item_ids: list[ResumeItemId] = []
    for experience in resume.experiences:
        item_ids.append(experience.id)
        item_ids.extend(bullet.id for bullet in experience.bullets)
    for item in (
        *resume.skills,
        *resume.education,
        *resume.projects,
        *resume.certifications,
        *resume.languages,
        *resume.additional_sections,
    ):
        item_ids.append(item.id)
    for item in resume.education:
        item_ids.extend(detail.id for detail in item.details)
    for item in resume.projects:
        item_ids.extend(bullet.id for bullet in item.bullets)
    for section in resume.additional_sections:
        item_ids.extend(item.id for item in section.items)
    return item_ids


def _all_evidence_references(resume: MasterResume | FinalResume) -> list[EvidenceId]:
    references: list[EvidenceId] = []
    if resume.summary is not None:
        references.extend(resume.summary.evidence_ids)
    for experience in resume.experiences:
        for bullet in experience.bullets:
            references.extend(bullet.evidence_ids)
    for skill in resume.skills:
        references.extend(skill.evidence_ids)
    for item in resume.education:
        for detail in item.details:
            references.extend(detail.evidence_ids)
    for item in resume.projects:
        for bullet in item.bullets:
            references.extend(bullet.evidence_ids)
    for item in (*resume.certifications, *resume.languages):
        references.extend(item.evidence_ids)
    for section in resume.additional_sections:
        for item in section.items:
            references.extend(item.evidence_ids)
    return references


def _validate_resume_graph(resume: MasterResume | FinalResume) -> None:
    _require_unique(resume.section_order, "sectionOrder")
    expected_sections = _present_sections(resume)
    actual_sections = set(resume.section_order)
    if actual_sections != expected_sections:
        missing = sorted(expected_sections - actual_sections)
        unexpected = sorted(actual_sections - expected_sections)
        raise ValueError(
            f"sectionOrder must contain every non-empty section exactly once; "
            f"missing={missing}, unexpected={unexpected}"
        )

    _require_unique(_all_item_ids(resume), "resume item IDs")
    evidence_ids = [item.id for item in resume.evidence]
    _require_unique(evidence_ids, "evidence IDs")
    unknown_evidence_ids = sorted(set(_all_evidence_references(resume)) - set(evidence_ids))
    if unknown_evidence_ids:
        raise ValueError(
            f"resume content references unknown evidence IDs: {unknown_evidence_ids}"
        )


# Explicit domain aliases used by generation and persistence boundaries.
CanonicalMasterResume = MasterResume
TailoredResume = FinalResume
Evidence = ResumeEvidence


__all__ = [
    "AdditionalResumeSection",
    "CanonicalId",
    "CanonicalMasterResume",
    "Evidence",
    "EvidenceBackedText",
    "EvidenceClaimType",
    "EvidenceId",
    "ExperienceId",
    "ExperienceRewrite",
    "FinalResume",
    "JobId",
    "MasterCertification",
    "MasterEducation",
    "MasterExperience",
    "MasterLanguage",
    "MasterProject",
    "MasterResume",
    "MasterSkill",
    "ResumeBasics",
    "ResumeBullet",
    "ResumeEvidence",
    "ResumeId",
    "ResumeItemId",
    "ResumeSectionName",
    "RewrittenExperience",
    "StrictResumeModel",
    "TailoredResume",
]
