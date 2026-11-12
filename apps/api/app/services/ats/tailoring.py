"""One tailoring session: plan, model wording with fact checks, assembly and report.

The session is pure: it builds prompts and consumes model responses but never
calls a backend or a database. The workflow runs the requests of one round in
parallel and feeds the responses back. A tailored resume is assembled from the
profile, so roles, dates, education, languages and skills are never model text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from app.models.generation_workflow import CoverLetterDraft
from app.models.resume import (
    FinalResume,
    MasterEducation,
    MasterExperience,
    MasterResume,
    MasterSkill,
    resume_evidence_ids,
)
from app.services.ats.cover_letter import (
    LetterDraft,
    build_cover_letter_prompt,
    evaluate_cover_letter,
    parse_letter_draft,
)
from app.services.ats.models import JobTarget
from app.services.ats.planner import (
    CoverageScore,
    DocumentLanguage,
    PlannedStatement,
    TailoringPlan,
    build_tailoring_plan,
    coverage_score,
)
from app.services.ats.profile_index import (
    ProfileIndex,
    build_profile_index,
    split_statement_texts,
)
from app.services.ats.skill_dictionary import SkillDictionary, default_skill_dictionary
from app.services.ats.wording import (
    WordedStatement,
    WordingDraft,
    build_wording_prompt,
    evaluate_summary,
    evaluate_wording,
    language_code,
    master_wording,
    parse_wording_draft,
)
from app.services.resume_skills import order_skill_categories, source_skill_category

WORDING_BATCH_SIZE = 14
PRESENT_LABELS: dict[DocumentLanguage, str] = {"en": "Present", "de": "heute", "fr": "présent"}
UNDATED_PERIOD = "–"
# Free-form profile notes are context for the candidate, not resume sections.
PRIVATE_SECTION_IDS = frozenset({"profile-additional_notes", "profile-personal_site"})
_SECTION_PRIORITY = {
    section: index
    for index, section in enumerate(("summary", "experience", "education", "languages", "skills"))
}

RequestKind = Literal["wording", "cover_letter"]


@dataclass(frozen=True)
class ModelRequest:
    kind: RequestKind
    label: str
    prompt: str
    response_model: type[BaseModel]
    statement_ids: tuple[str, ...] = ()
    include_summary: bool = False


@dataclass(frozen=True)
class ModelResponse:
    """Structured data of one request, or the reason the request failed."""

    data: object | None = None
    error: str = ""


@dataclass(frozen=True)
class VacancyContext:
    job_id: str
    title: str
    company: str
    location: str
    text: str


@dataclass(frozen=True)
class TailoringResult:
    resume: FinalResume | None
    cover_letter: CoverLetterDraft | None
    drop_order: tuple[str, ...]
    report: dict[str, Any]
    warnings: tuple[str, ...]


class TailoringError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def period_text(experience: MasterExperience, language: DocumentLanguage) -> str:
    start = experience.start_date.strip()
    end = PRESENT_LABELS[language] if experience.is_current else experience.end_date.strip()
    if start and end:
        return f"{start} – {end}"
    return start or end or UNDATED_PERIOD


def tailored_skills(master: MasterResume, skill_order: Sequence[str]) -> list[MasterSkill]:
    """Every profile skill in the planned order, grouped by the product's categories."""
    by_id = {skill.id: skill for skill in master.skills}
    ordered = [by_id[skill_id] for skill_id in skill_order if skill_id in by_id]
    ordered += [skill for skill in master.skills if skill.id not in set(skill_order)]
    return order_skill_categories(
        [
            skill.model_copy(deep=True, update={"category": source_skill_category(skill)})
            for skill in ordered
        ]
    )


def _education_payload(item: MasterEducation) -> dict[str, Any]:
    """Education as in the profile, with a multi-line description shown line by line."""
    payload = item.model_dump(mode="json", by_alias=True)
    details: list[dict[str, Any]] = []
    for detail in item.details:
        lines = split_statement_texts(detail.text)
        for number, line in enumerate(lines, start=1):
            details.append(
                {
                    "id": detail.id if len(lines) == 1 else f"{detail.id}-p{number}",
                    "text": line,
                    "evidenceIds": list(detail.evidence_ids),
                }
            )
    payload["details"] = details
    return payload


def assemble_resume(
    master: MasterResume,
    plan: TailoringPlan,
    wording: dict[str, WordedStatement],
    *,
    summary: str,
    resume_id: str,
    target_job_id: str,
) -> FinalResume:
    """Build the tailored resume from profile data and the accepted wording."""
    roles = {experience.id: experience for experience in master.experiences}
    experiences: list[dict[str, Any]] = []
    for planned in plan.experiences:
        role = roles[planned.experience_id]
        bullets = []
        for item in planned.statements:
            worded = wording.get(item.statement.id) or master_wording(item)
            bullets.append(
                {
                    "id": item.statement.id,
                    "text": worded.text,
                    "evidenceIds": list(item.statement.evidence_ids),
                    "emphasis": list(worded.emphasis),
                }
            )
        if not bullets:
            continue
        experiences.append(
            {
                "id": f"tailored-{role.id}",
                "masterExperienceId": role.id,
                "company": role.company,
                "title": role.title,
                "location": role.location,
                "period": period_text(role, plan.language),
                "bullets": bullets,
            }
        )

    summary_block: dict[str, Any] | None = None
    if summary:
        evidence_ids = (
            list(master.summary.evidence_ids)
            if master.summary is not None
            else list(
                dict.fromkeys(
                    evidence_id
                    for item in plan.statements[:3]
                    for evidence_id in item.statement.evidence_ids
                )
            )[:20]
        )
        if evidence_ids:
            summary_block = {"text": summary, "evidenceIds": evidence_ids}

    section_order = [section for section in master.section_order if section != "summary"]
    if all(item.id in PRIVATE_SECTION_IDS for item in master.additional_sections):
        section_order = [section for section in section_order if section != "additional"]
    if summary_block is not None:
        section_order.insert(0, "summary")
    if experiences and "experience" not in section_order:
        section_order.append("experience")
    section_order.sort(key=lambda section: _SECTION_PRIORITY.get(section, len(_SECTION_PRIORITY)))

    payload: dict[str, Any] = {
        "schemaVersion": "1.0",
        "id": resume_id,
        "masterResumeId": master.id,
        "targetJobId": target_job_id,
        "language": plan.language,
        "basics": {
            **master.basics.model_dump(mode="json", by_alias=True),
            "headline": plan.headline or master.basics.headline,
        },
        "summary": summary_block,
        "experiences": experiences,
        "skills": [
            skill.model_dump(mode="json", by_alias=True)
            for skill in tailored_skills(master, plan.skill_order)
        ],
        "education": [_education_payload(item) for item in master.education],
        "projects": [item.model_dump(mode="json", by_alias=True) for item in master.projects],
        "certifications": [
            item.model_dump(mode="json", by_alias=True) for item in master.certifications
        ],
        "languages": [item.model_dump(mode="json", by_alias=True) for item in master.languages],
        "additionalSections": [
            item.model_dump(mode="json", by_alias=True)
            for item in master.additional_sections
            if item.id not in PRIVATE_SECTION_IDS
        ],
        "sectionOrder": section_order,
        "evidence": [item.model_dump(mode="json", by_alias=True) for item in master.evidence],
    }
    draft = FinalResume.model_validate(payload)
    referenced = set(resume_evidence_ids(draft))
    payload["evidence"] = [
        item.model_dump(mode="json", by_alias=True)
        for item in master.evidence
        if item.id in referenced
    ] or payload["evidence"][:1]
    return FinalResume.model_validate(payload)


_LANGUAGE_NAMES: dict[str, tuple[str, ...]] = {
    "en": ("english", "englisch", "anglais", "inglese"),
    "de": ("german", "deutsch", "allemand", "tedesco"),
    "fr": ("french", "französisch", "franzoesisch", "français", "francais", "francese"),
    "it": ("italian", "italienisch", "italien", "italiano"),
}
_CEFR_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "native": 7}
_CEFR_LEVEL = re.compile(r"(?<![A-Za-z0-9])([ABC][12])(?![A-Za-z0-9])")
_NATIVE_WORDS = ("native", "mother", "muttersprache", "maternelle", "bilingual")
_FLUENT_WORDS = ("fluent", "fliessend", "fließend", "verhandlungssicher", "courant")


def profile_language_level(master: MasterResume, language: str) -> str | None:
    """CEFR level the profile states for a language, if it can be read."""
    names = _LANGUAGE_NAMES.get(language, ())
    for item in master.languages:
        if not item.name.strip().casefold().startswith(names):
            continue
        proficiency = item.proficiency
        if match := _CEFR_LEVEL.search(proficiency.upper()):
            return match[1]
        lowered = proficiency.casefold()
        if any(word in lowered for word in _NATIVE_WORDS):
            return "native"
        if any(word in lowered for word in _FLUENT_WORDS):
            return "C1"
        return None
    return None


def evaluate_knockouts(
    target: JobTarget,
    master: MasterResume,
    index: ProfileIndex,
) -> list[dict[str, Any]]:
    """Hard requirements of the posting, checked where the profile has the data.

    `met` is true or false only for total experience and for language levels;
    everything else stays null so the person checks it.
    """
    results: list[dict[str, Any]] = []
    for knockout in target.knockouts:
        met: bool | None = None
        detail = ""
        if knockout.kind == "experience" and knockout.years is not None:
            met = index.total_months >= knockout.years * 12
            detail = f"Profile: {index.total_months // 12} years {index.total_months % 12} months"
        elif knockout.kind == "language" and knockout.language and knockout.cefr_level:
            level = profile_language_level(master, knockout.language)
            if level is not None:
                met = _CEFR_RANK[level] >= _CEFR_RANK[knockout.cefr_level]
                detail = f"Profile: {level}"
            elif not any(
                item.name.strip().casefold().startswith(_LANGUAGE_NAMES.get(knockout.language, ()))
                for item in master.languages
            ):
                met = False
                detail = "Not in the profile"
        results.append(
            {
                "kind": knockout.kind,
                "requirement": knockout.requirement,
                "met": met,
                "detail": detail,
            }
        )
    return results


def resume_coverage(
    target: JobTarget,
    *,
    bullets: Sequence[str],
    summary: str,
    headline: str,
    skills: Sequence[str],
    dictionary: SkillDictionary,
) -> CoverageScore:
    return coverage_score(
        target,
        experience_text="\n".join([summary, *bullets]),
        skills_text="\n".join([headline, ", ".join(skills)]),
        dictionary=dictionary,
    )


@dataclass
class TailoringSession:
    """State of one run between model rounds."""

    master: MasterResume
    target: JobTarget
    vacancy: VacancyContext
    document_types: tuple[str, ...]
    language: str = "Auto"
    user_preferences: str = ""
    resume_id: str = "tailored-resume"
    letter_id: str = "cover-letter"
    today: date | None = None
    dictionary: SkillDictionary = field(default_factory=default_skill_dictionary)

    index: ProfileIndex = field(init=False)
    plan: TailoringPlan = field(init=False)
    wording: dict[str, WordedStatement] = field(init=False, default_factory=dict)
    rejected: dict[str, tuple[str, ...]] = field(init=False, default_factory=dict)
    summary: str = field(init=False, default="")
    summary_issues: tuple[str, ...] = field(init=False, default=())
    letter: CoverLetterDraft | None = field(init=False, default=None)
    letter_issues: dict[int, tuple[str, ...]] = field(init=False, default_factory=dict)
    warnings: list[str] = field(init=False, default_factory=list)
    _summary_pending: bool = field(init=False, default=False)
    _letter_pending: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.index = build_profile_index(self.master, dictionary=self.dictionary, today=self.today)
        self.plan = build_tailoring_plan(
            self.master,
            self.index,
            self.target,
            language=self.language,
            dictionary=self.dictionary,
        )
        self._summary_pending = self.wants_resume
        self._letter_pending = self.wants_letter

    @property
    def wants_resume(self) -> bool:
        return "tailored_resume" in self.document_types

    @property
    def wants_letter(self) -> bool:
        return "cover_letter" in self.document_types

    @property
    def translated(self) -> bool:
        return self.plan.language != language_code(self.master.language)

    # --- Requests -------------------------------------------------------------

    def first_round(self) -> list[ModelRequest]:
        requests: list[ModelRequest] = []
        if self.wants_resume:
            statements = list(self.plan.statements)
            batches = [
                statements[start : start + WORDING_BATCH_SIZE]
                for start in range(0, len(statements), WORDING_BATCH_SIZE)
            ] or [[]]
            for number, batch in enumerate(batches, start=1):
                requests.append(self._wording_request(batch, f"wording-{number}", number == 1))
        if self.wants_letter:
            requests.append(self._letter_request("cover-letter"))
        return requests

    def retry_round(self) -> list[ModelRequest]:
        """Requests for what the first round left rejected; empty when nothing is."""
        requests: list[ModelRequest] = []
        retry_statements = [
            planned for planned in self.plan.statements if planned.statement.id in self.rejected
        ]
        if self.wants_resume and (retry_statements or self._summary_pending):
            requests.append(
                self._wording_request(
                    retry_statements,
                    "wording-retry",
                    self._summary_pending,
                    retry_issues=self.rejected,
                )
            )
        if self.wants_letter and self._letter_pending:
            requests.append(self._letter_request("cover-letter-retry", self.letter_issues))
        return requests

    def _wording_request(
        self,
        statements: Sequence[PlannedStatement],
        label: str,
        include_summary: bool,
        *,
        retry_issues: dict[str, tuple[str, ...]] | None = None,
    ) -> ModelRequest:
        return ModelRequest(
            kind="wording",
            label=label,
            prompt=build_wording_prompt(
                master=self.master,
                index=self.index,
                target=self.target,
                plan=self.plan,
                statements=statements,
                user_preferences=self.user_preferences,
                retry_issues=retry_issues,
                include_summary=include_summary,
            ),
            response_model=WordingDraft,
            statement_ids=tuple(planned.statement.id for planned in statements),
            include_summary=include_summary,
        )

    def _letter_request(
        self,
        label: str,
        retry_issues: dict[int, tuple[str, ...]] | None = None,
    ) -> ModelRequest:
        return ModelRequest(
            kind="cover_letter",
            label=label,
            prompt=build_cover_letter_prompt(
                master=self.master,
                index=self.index,
                target=self.target,
                plan=self.plan,
                company=self.vacancy.company,
                user_preferences=self.user_preferences,
                retry_issues=retry_issues or None,
            ),
            response_model=LetterDraft,
        )

    # --- Responses ------------------------------------------------------------

    def apply(self, requests: Sequence[ModelRequest], responses: Sequence[ModelResponse]) -> None:
        """Check one round of responses and keep what passes the fact guard."""
        if len(requests) != len(responses):
            raise ValueError("Every model request needs exactly one response")
        for request, response in zip(requests, responses, strict=True):
            if request.kind == "wording":
                self._apply_wording(request, response)
            else:
                self._apply_letter(response)

    def _apply_wording(self, request: ModelRequest, response: ModelResponse) -> None:
        planned = [
            item for item in self.plan.statements if item.statement.id in request.statement_ids
        ]
        try:
            if response.data is None:
                raise ValueError(response.error or "no response")
            draft = parse_wording_draft(response.data)
        except ValueError as exc:
            for item in planned:
                self.rejected[item.statement.id] = (f"model request failed: {exc}",)
            if request.include_summary:
                self.summary_issues = (f"model request failed: {exc}",)
            return
        accepted, rejected = evaluate_wording(
            draft,
            master=self.master,
            plan=self.plan,
            statements=planned,
            dictionary=self.dictionary,
            vacancy_text=self.vacancy.text,
            index=self.index,
        )
        self.wording.update(accepted)
        for statement_id in accepted:
            self.rejected.pop(statement_id, None)
        self.rejected.update(rejected)
        if request.include_summary:
            summary, issues = evaluate_summary(
                draft.summary,
                master=self.master,
                index=self.index,
                plan=self.plan,
                dictionary=self.dictionary,
                vacancy_text=self.vacancy.text,
            )
            self.summary_issues = issues
            if summary:
                self.summary = summary
                self._summary_pending = False

    def _apply_letter(self, response: ModelResponse) -> None:
        try:
            if response.data is None:
                raise ValueError(response.error or "no response")
            draft = parse_letter_draft(response.data)
        except ValueError as exc:
            self.letter_issues = {0: (f"model request failed: {exc}",)}
            return
        evaluation = evaluate_cover_letter(
            draft,
            master=self.master,
            index=self.index,
            target=self.target,
            plan=self.plan,
            dictionary=self.dictionary,
            letter_id=self.letter_id,
            target_job_id=self.vacancy.job_id,
            company=self.vacancy.company,
            location=self.vacancy.location,
            vacancy_text=self.vacancy.text,
        )
        self.letter_issues = evaluation.issues
        if evaluation.letter is not None:
            self.letter = evaluation.letter
            self._letter_pending = False

    # --- Result ---------------------------------------------------------------

    def finish(self) -> TailoringResult:
        resume: FinalResume | None = None
        if self.wants_resume:
            if not self.wording and self.plan.statements:
                reason = next(iter(self.rejected.values()), ("no response",))[0]
                raise TailoringError(
                    f"The model did not return usable resume wording ({reason}).",
                    code="wording_failed",
                    retryable=True,
                )
            summary = self.summary
            if not summary and self.master.summary is not None and not self.translated:
                summary = self.master.summary.text
            resume = assemble_resume(
                self.master,
                self.plan,
                self.wording,
                summary=summary,
                resume_id=self.resume_id,
                target_job_id=self.vacancy.job_id,
            )
            kept = [item for item in self.plan.statements if item.statement.id not in self.wording]
            if kept:
                self.warnings.append(
                    f"{len(kept)} statement(s) keep the profile wording because the "
                    "rewritten text did not pass the fact check."
                )
        if self.wants_letter and self.letter is None:
            if not self.wants_resume:
                reason = next(iter(self.letter_issues.values()), ("no response",))[0]
                raise TailoringError(
                    f"The cover letter did not pass the fact check ({reason}).",
                    code="cover_letter_failed",
                    retryable=True,
                )
            self.warnings.append(
                "The cover letter was not created because its text did not pass the fact "
                "check. Start a new run to try again."
            )
        return TailoringResult(
            resume=resume,
            cover_letter=self.letter,
            drop_order=self.plan.drop_order,
            report=self.report(resume),
            warnings=tuple(self.warnings),
        )

    def report(self, resume: FinalResume | None) -> dict[str, Any]:
        """What the user sees next to the document: score, coverage, changes and gaps."""
        before = resume_coverage(
            self.target,
            bullets=[statement.text for statement in self.index.statements],
            summary=self.master.summary.text if self.master.summary else "",
            headline=self.master.basics.headline,
            skills=[skill.name for skill in self.master.skills],
            dictionary=self.dictionary,
        )
        after = (
            resume_coverage(
                self.target,
                bullets=[
                    bullet.text for experience in resume.experiences for bullet in experience.bullets
                ],
                summary=resume.summary.text if resume.summary else "",
                headline=resume.basics.headline,
                skills=[skill.name for skill in resume.skills],
                dictionary=self.dictionary,
            )
            if resume is not None
            else before
        )
        before_status = {item.label: item.status for item in before.items}
        selected = len(self.plan.statements)
        reworded = sum(
            1
            for planned in self.plan.statements
            if (worded := self.wording.get(planned.statement.id)) is not None
            and worded.text != planned.statement.text
        )
        kept_original = [
            {"id": planned.statement.id, "reasons": list(self.rejected.get(planned.statement.id, ()))}
            for planned in self.plan.statements
            if self.wants_resume and planned.statement.id not in self.wording
        ]
        adopted_terms = [term for planned in self.plan.statements for term in planned.terms]
        return {
            "language": self.plan.language,
            "headline": self.plan.headline,
            "vacancy": {
                "title": self.target.title,
                "seniority": self.target.seniority,
                "language": self.target.language,
                "parsedBy": self.target.model or "dictionary",
            },
            "score": {"before": before.score, "after": after.score},
            "coverage": [
                {
                    "label": item.label,
                    "importance": item.importance,
                    "before": before_status.get(item.label, "missing"),
                    "after": item.status,
                }
                for item in after.items
            ],
            "gaps": [
                {"label": match.label, "importance": match.importance}
                for match in self.plan.matches
                if match.support == "gap"
            ],
            "knockouts": evaluate_knockouts(self.target, self.master, self.index),
            "statements": {
                "inProfile": len(self.index.statements),
                "selected": selected,
                "reworded": reworded,
                "keptOriginal": len(kept_original),
                "omitted": len(self.plan.excluded_statement_ids),
            },
            "keptOriginal": kept_original,
            "changes": self._changes(reworded=reworded, adopted_terms=adopted_terms),
            "summaryIssues": list(self.summary_issues) if not self.summary else [],
            "coverLetterIssues": [
                reason for reasons in self.letter_issues.values() for reason in reasons
            ]
            if self.letter is None and self.wants_letter
            else [],
        }

    def _changes(self, *, reworded: int, adopted_terms: Sequence[str]) -> list[str]:
        changes: list[str] = []
        if not self.wants_resume:
            return changes
        if self.plan.headline and self.plan.headline != self.master.basics.headline:
            changes.append(f"Headline set to “{self.plan.headline}”.")
        if reworded:
            changes.append(
                f"Reworded {reworded} of {len(self.plan.statements)} statements for this vacancy; "
                "every number and technology was checked against your profile."
            )
        if adopted_terms:
            shown = ", ".join(dict.fromkeys(adopted_terms))
            changes.append(f"Used the vacancy's own spelling for: {shown}.")
        omitted = len(self.plan.excluded_statement_ids)
        if omitted:
            changes.append(f"Left out {omitted} statement(s) that do not relate to this vacancy.")
        leading = [
            skill.name
            for skill in tailored_skills(self.master, self.plan.skill_order)
            if any(
                match.support != "gap"
                and (
                    (resolved := self.dictionary.lookup(skill.name)) is not None
                    and resolved == match.canonical_id
                )
                for match in self.plan.matches
            )
        ][:6]
        if leading:
            changes.append(f"Moved the skills the vacancy asks for to the front: {', '.join(leading)}.")
        if self.translated and self.wants_resume:
            changes.append("Wrote the statements in the language of the vacancy.")
        return changes


__all__ = [
    "PRESENT_LABELS",
    "UNDATED_PERIOD",
    "ModelRequest",
    "ModelResponse",
    "TailoringError",
    "TailoringResult",
    "TailoringSession",
    "VacancyContext",
    "assemble_resume",
    "evaluate_knockouts",
    "period_text",
    "profile_language_level",
    "resume_coverage",
    "tailored_skills",
]
