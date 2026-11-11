"""Deterministic tailoring plan: which profile facts go into the resume, and where.

The planner never writes text. It ranks the statements of every role against
the vacancy target, decides the display order and what may be dropped under page
pressure, tells the wording step which vacancy terms a statement may adopt, and
reports how well the vacancy's skills are covered before and after tailoring.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.models.resume import MasterResume, MasterSkill
from app.services.ats.job_target import clean_title
from app.services.ats.models import JobSkill, JobTarget
from app.services.ats.profile_index import ProfileIndex, ProfileStatement
from app.services.ats.skill_dictionary import (
    SkillDictionary,
    alias_key,
    default_skill_dictionary,
    normalize_text,
)
from app.services.resume_skills import order_skill_categories

SkillSupport = Literal["experience", "profile", "gap"]
CoverageStatus = Literal["experience", "skills", "missing"]
DocumentLanguage = Literal["en", "de", "fr"]

MAX_STATEMENTS_PER_ROLE = 8
MAX_TERMS_PER_STATEMENT = 2
MAX_HEADLINE_SKILLS = 3
MAX_HEADLINE_CHARS = 90
_IMPORTANCE_WEIGHT = {"required": 3.0, "preferred": 1.5}
_COVERAGE_WEIGHT = {"required": 3.0, "preferred": 1.0}
_EXPERIENCE_CREDIT = 1.0
_SYNONYM_CREDIT = 0.8
_SKILLS_SECTION_CREDIT = 0.6
_WORD = re.compile(r"[^\W\d_]{4,}")
_ROLE_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({
        "engineer", "developer", "entwickler", "entwicklerin", "ingenieur", "ingenieurin",
        "programmer", "programmierer", "développeur", "ingénieur", "softwareentwickler",
        "softwareentwicklerin", "softwareingenieur",
    }),
    frozenset({"architect", "architekt", "architektin", "architecte"}),
    frozenset({"analyst", "analystin", "analyste"}),
    frozenset({"scientist", "wissenschaftler", "wissenschaftlerin"}),
    frozenset({"administrator", "admin", "sysadmin", "systemadministrator"}),
    frozenset({"consultant", "berater", "beraterin"}),
    frozenset({"manager", "managerin", "leiter", "leiterin", "lead"}),
    frozenset({"designer", "designerin"}),
    frozenset({"tester", "testerin", "qa"}),
)
_SENIORITY_WORDS = frozenset({
    "senior", "sr", "junior", "jr", "lead", "principal", "staff", "head", "chief", "intern",
    "internship", "trainee", "praktikant", "praktikantin", "praktikum", "werkstudent",
    "werkstudentin", "graduate", "mid", "intermediate",
})
_COMMON_WORDS = frozenset({
    "with", "that", "this", "from", "have", "will", "your", "their", "team", "teams", "work",
    "working", "experience", "knowledge", "skills", "strong", "good", "sowie", "eine", "einer",
    "oder", "und", "mit", "für", "auch", "sind", "wird", "werden", "unsere", "unser", "dein",
    "deine", "ihre", "über", "avec", "pour", "dans", "vous", "nous", "des", "les",
})


@dataclass(frozen=True)
class SkillMatch:
    """How one vacancy skill is supported by the profile."""

    key: str
    label: str
    canonical_id: str | None
    importance: Literal["required", "preferred"]
    support: SkillSupport
    statement_ids: tuple[str, ...]
    months: int


@dataclass(frozen=True)
class PlannedStatement:
    statement: ProfileStatement
    score: float
    # Vacancy spellings the wording may adopt because the statement already
    # names the same skill differently.
    terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedExperience:
    experience_id: str
    statements: tuple[PlannedStatement, ...]
    allowed_technologies: tuple[str, ...]


@dataclass(frozen=True)
class CoverageItem:
    label: str
    importance: Literal["required", "preferred"]
    status: CoverageStatus


@dataclass(frozen=True)
class CoverageScore:
    """Share of the vacancy's skills a reader finds in the resume, 0 to 100."""

    score: int | None
    items: tuple[CoverageItem, ...]

    def count(self, importance: str, *, covered: bool) -> int:
        return sum(
            1
            for item in self.items
            if item.importance == importance and (item.status != "missing") is covered
        )


@dataclass(frozen=True)
class TailoringPlan:
    language: DocumentLanguage
    headline: str
    experiences: tuple[PlannedExperience, ...]
    skill_order: tuple[str, ...]
    matches: tuple[SkillMatch, ...]
    drop_order: tuple[str, ...]
    excluded_statement_ids: tuple[str, ...]

    @property
    def statements(self) -> tuple[PlannedStatement, ...]:
        return tuple(item for experience in self.experiences for item in experience.statements)

    @property
    def gaps(self) -> tuple[SkillMatch, ...]:
        return tuple(
            match
            for match in self.matches
            if match.support == "gap" and match.importance == "required"
        )


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w+#]){re.escape(normalize_text(term))}(?![\w+#])", re.IGNORECASE)


def mentions_term(text: str, term: str) -> bool:
    return bool(_term_pattern(term).search(normalize_text(text)))


def _keywords(texts: Iterable[str]) -> frozenset[str]:
    return frozenset(
        word
        for text in texts
        for word in (match.group().casefold() for match in _WORD.finditer(text))
        if word not in _COMMON_WORDS
    )


def _phrase_words(phrase: str) -> list[str]:
    return [match.group().casefold() for match in _WORD.finditer(phrase)]


def _statement_supports(statement: ProfileStatement, skill: JobSkill) -> bool:
    if skill.canonical_id is not None:
        return skill.canonical_id in statement.skill_ids
    if mentions_term(statement.text, skill.surface_form):
        return True
    # A phrase outside the dictionary ("data pipelines") is also supported by a
    # statement that uses all of its words ("pipelines ... retail data").
    words = _phrase_words(skill.surface_form)
    return len(words) >= 2 and set(words) <= set(_phrase_words(statement.text))


def match_skills(target: JobTarget, index: ProfileIndex) -> tuple[SkillMatch, ...]:
    matches: list[SkillMatch] = []
    for skill in target.skills:
        statement_ids = tuple(
            statement.id for statement in index.statements if _statement_supports(statement, skill)
        )
        depth = index.skills.get(skill.canonical_id) if skill.canonical_id else None
        used_in_role = bool(depth and depth.experience_ids)
        if statement_ids or used_in_role:
            support: SkillSupport = "experience"
        elif index.knows(skill.canonical_id, skill.surface_form):
            support = "profile"
        else:
            support = "gap"
        matches.append(
            SkillMatch(
                key=skill.key,
                label=skill.surface_form,
                canonical_id=skill.canonical_id,
                importance=skill.importance,
                support=support,
                statement_ids=statement_ids,
                months=depth.months if depth else 0,
            )
        )
    return tuple(matches)


def _statement_score(
    statement: ProfileStatement,
    *,
    target: JobTarget,
    responsibility_keywords: frozenset[str],
    role_position: int,
) -> tuple[float, bool]:
    """Value of a statement for this vacancy, and whether it is relevant at all."""
    skill_score = 0.0
    for skill in target.skills:
        if _statement_supports(statement, skill):
            emphasis = 1 + min(skill.frequency - 1, 2) * 0.15
            skill_score += _IMPORTANCE_WEIGHT[skill.importance] * emphasis
    overlap = len(_keywords([statement.text]) & responsibility_keywords)
    topic_score = min(overlap, 4) * 0.4
    relevant = skill_score > 0 or overlap >= 2
    score = skill_score + topic_score
    if statement.has_metric:
        score += 0.8
    score += {0: 0.4, 1: 0.2}.get(role_position, 0.0)
    return round(score, 3), relevant


def resolve_document_language(
    requested: str,
    *,
    target: JobTarget,
    master: MasterResume,
) -> DocumentLanguage:
    """Explicit choice first, then the posting's language, then the profile's."""

    def code(value: str) -> DocumentLanguage | None:
        text = value.strip().casefold()
        if text.startswith(("de", "german", "deutsch")):
            return "de"
        if text.startswith(("fr", "french", "français", "francais")):
            return "fr"
        if text.startswith(("en", "english", "englisch")):
            return "en"
        return None

    return code(requested) or code(target.language) or code(master.language) or "en"


def _role_family(words: Iterable[str]) -> frozenset[str] | None:
    lowered = {word.casefold() for word in words}
    return next((family for family in _ROLE_FAMILIES if lowered & family), None)


def _title_words(title: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:[+#.]+[^\W_]*)*", normalize_text(title))


def plan_headline(
    master: MasterResume,
    target: JobTarget,
    matches: Sequence[SkillMatch],
) -> str:
    """Adopt the vacancy title only when the candidate has held that kind of role.

    Seniority words of the vacancy are kept only if one of the candidate's own
    titles carries them. Otherwise the profile's own headline stays.
    """
    own_titles = [master.basics.headline, *(experience.title for experience in master.experiences)]
    own_words = {word.casefold() for title in own_titles for word in _title_words(title)}
    own_family = _role_family(own_words)
    # Only the role name of the posting title: "Senior Backend Engineer (Python) - Zurich".
    vacancy_head = re.split(r"\s+[-–—|·/]\s+|\s*[,(]", clean_title(target.title))[0].strip()
    base = master.basics.headline or (master.experiences[0].title if master.experiences else "")
    base = re.split(r"\s+[|·]\s+", base)[0].strip()
    if own_family is not None and own_family == _role_family(_title_words(vacancy_head)):
        kept = [
            word
            for word in vacancy_head.split()
            if word.casefold().strip(".") not in _SENIORITY_WORDS or word.casefold() in own_words
        ]
        candidate = " ".join(kept).strip()
        if len(candidate) >= 3:
            base = candidate
    extras: list[str] = []
    for match in matches:
        if len(extras) >= MAX_HEADLINE_SKILLS:
            break
        if (
            match.importance == "required"
            and match.support == "experience"
            and not mentions_term(base, match.label)
            and len(match.label) <= 24
        ):
            extras.append(match.label)
    headline = f"{base} | {', '.join(extras)}" if base and extras else base
    return headline if len(headline) <= MAX_HEADLINE_CHARS else base


def _skill_rank(
    skill: MasterSkill,
    *,
    target: JobTarget,
    dictionary: SkillDictionary,
) -> int:
    canonical = dictionary.lookup(skill.name)
    key = alias_key(skill.name)
    rank = 2
    for job_skill in target.skills:
        same = (
            canonical is not None and job_skill.canonical_id == canonical
        ) or alias_key(job_skill.surface_form) == key
        if same:
            rank = min(rank, 0 if job_skill.importance == "required" else 1)
    return rank


def plan_skill_order(
    master: MasterResume,
    target: JobTarget,
    *,
    dictionary: SkillDictionary,
) -> tuple[str, ...]:
    """Vacancy skills first inside each category; categories keep the product order."""
    ranked = sorted(
        enumerate(master.skills),
        key=lambda item: (_skill_rank(item[1], target=target, dictionary=dictionary), item[0]),
    )
    return tuple(skill.id for skill in order_skill_categories([skill for _, skill in ranked]))


def build_tailoring_plan(
    master: MasterResume,
    index: ProfileIndex,
    target: JobTarget,
    *,
    language: str = "Auto",
    dictionary: SkillDictionary | None = None,
) -> TailoringPlan:
    dictionary = dictionary or default_skill_dictionary()
    matches = match_skills(target, index)
    responsibility_keywords = _keywords([target.title, *target.responsibilities])

    experiences: list[PlannedExperience] = []
    excluded: list[str] = []
    protected: set[str] = set()
    scored: list[PlannedStatement] = []
    for position, experience in enumerate(master.experiences):
        ranked: list[tuple[PlannedStatement, bool]] = []
        for statement in index.statements_for(experience.id):
            score, relevant = _statement_score(
                statement,
                target=target,
                responsibility_keywords=responsibility_keywords,
                role_position=position,
            )
            ranked.append((PlannedStatement(statement=statement, score=score), relevant))
        ranked.sort(key=lambda item: (-item[0].score, item[0].statement.order))
        selected: list[PlannedStatement] = []
        for rank, (planned, relevant) in enumerate(ranked):
            # The two best statements of a role always stay. Beyond them, a
            # statement needs a link to the vacancy or a measurable result.
            keep = rank < 2 or relevant or planned.statement.has_metric
            if keep and len(selected) < MAX_STATEMENTS_PER_ROLE:
                selected.append(planned)
            else:
                excluded.append(planned.statement.id)
        if selected:
            protected.add(selected[0].statement.id)
        scored.extend(selected)
        experiences.append(
            PlannedExperience(
                experience_id=experience.id,
                statements=tuple(selected),
                allowed_technologies=index.experience_technology_names.get(experience.id, ()),
            )
        )

    experiences = _assign_terms(experiences, target)
    drop_order = tuple(
        planned.statement.id
        for planned in sorted(scored, key=lambda item: (item.score, -item.statement.order))
        if planned.statement.id not in protected
    )
    return TailoringPlan(
        language=resolve_document_language(language, target=target, master=master),
        headline=plan_headline(master, target, matches),
        experiences=tuple(experiences),
        skill_order=plan_skill_order(master, target, dictionary=dictionary),
        matches=matches,
        drop_order=drop_order,
        excluded_statement_ids=tuple(excluded),
    )


def _assign_terms(
    experiences: list[PlannedExperience],
    target: JobTarget,
) -> list[PlannedExperience]:
    """Give the vacancy's spelling to a statement that names the same skill otherwise."""
    selected = [planned for experience in experiences for planned in experience.statements]
    terms: dict[str, list[str]] = {}
    for skill in sorted(
        target.skills,
        key=lambda skill: (skill.importance != "required", -skill.frequency),
    ):
        if any(mentions_term(planned.statement.text, skill.surface_form) for planned in selected):
            continue
        candidates = [
            planned
            for planned in selected
            if _statement_supports(planned.statement, skill)
            and len(terms.get(planned.statement.id, ())) < MAX_TERMS_PER_STATEMENT
        ]
        if candidates:
            best = max(candidates, key=lambda planned: planned.score)
            terms.setdefault(best.statement.id, []).append(skill.surface_form)
    return [
        PlannedExperience(
            experience_id=experience.experience_id,
            statements=tuple(
                PlannedStatement(
                    statement=planned.statement,
                    score=planned.score,
                    terms=tuple(terms.get(planned.statement.id, ())),
                )
                for planned in experience.statements
            ),
            allowed_technologies=experience.allowed_technologies,
        )
        for experience in experiences
    ]


def coverage_score(
    target: JobTarget,
    *,
    experience_text: str,
    skills_text: str,
    dictionary: SkillDictionary | None = None,
) -> CoverageScore:
    """Weighted share of vacancy skills found in the document.

    The exact vacancy spelling in the experience counts fully, a synonym slightly
    less, and a skill that only appears in the skills list counts least.
    """
    dictionary = dictionary or default_skill_dictionary()
    experience_ids = {mention.skill_id for mention in dictionary.scan(experience_text)}
    skills_ids = {mention.skill_id for mention in dictionary.scan(skills_text)}
    for name in re.split(r"[,\n;|]", skills_text):
        if resolved := dictionary.lookup(name.strip()):
            skills_ids.add(resolved)
    items: list[CoverageItem] = []
    earned = 0.0
    possible = 0.0
    for skill in target.skills:
        weight = _COVERAGE_WEIGHT[skill.importance]
        possible += weight
        if mentions_term(experience_text, skill.surface_form):
            credit, status = _EXPERIENCE_CREDIT, "experience"
        elif skill.canonical_id is not None and skill.canonical_id in experience_ids:
            credit, status = _SYNONYM_CREDIT, "experience"
        elif mentions_term(skills_text, skill.surface_form) or (
            skill.canonical_id is not None and skill.canonical_id in skills_ids
        ):
            credit, status = _SKILLS_SECTION_CREDIT, "skills"
        else:
            credit, status = 0.0, "missing"
        earned += weight * credit
        items.append(
            CoverageItem(label=skill.surface_form, importance=skill.importance, status=status)
        )
    score = round(100 * earned / possible) if possible else None
    return CoverageScore(score=score, items=tuple(items))


__all__ = [
    "CoverageItem",
    "CoverageScore",
    "DocumentLanguage",
    "PlannedExperience",
    "PlannedStatement",
    "SkillMatch",
    "TailoringPlan",
    "build_tailoring_plan",
    "coverage_score",
    "match_skills",
    "mentions_term",
    "plan_headline",
    "plan_skill_order",
    "resolve_document_language",
]
