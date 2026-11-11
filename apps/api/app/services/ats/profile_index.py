"""Index of a master profile for tailoring: atomic statements, skills and their depth.

Everything here is deterministic and depends only on one immutable master
version. A statement is the smallest unit the planner can select: one bullet,
or one list item when a profile description holds several items in one bullet.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.models.resume import MasterExperience, MasterResume
from app.services.ats.skill_dictionary import (
    SkillDictionary,
    alias_key,
    default_skill_dictionary,
)

_LIST_MARKER = re.compile(r"(?m)^[ \t]*(?:[•●▪◦‣⁃*\-]|\d+[.)])[ \t]+")
_NUMBER = re.compile(r"\d")
_MONTHS = {
    name: month
    for month, names in enumerate(
        (
            ("jan", "january", "januar", "janvier"),
            ("feb", "february", "februar", "février", "fevrier"),
            ("mar", "march", "mär", "märz", "maerz", "mars"),
            ("apr", "april", "avril"),
            ("may", "mai"),
            ("jun", "june", "juni", "juin"),
            ("jul", "july", "juli", "juillet"),
            ("aug", "august", "août", "aout"),
            ("sep", "sept", "september", "septembre"),
            ("oct", "october", "okt", "oktober", "octobre"),
            ("nov", "november", "novembre"),
            ("dec", "december", "dez", "dezember", "décembre", "decembre"),
        ),
        start=1,
    )
    for name in names
}


@dataclass(frozen=True)
class ProfileStatement:
    """One selectable achievement of one role, with the facts it may be worded from."""

    id: str
    experience_id: str
    source_bullet_id: str
    text: str
    evidence_ids: tuple[str, ...]
    skill_ids: frozenset[str]
    has_metric: bool
    order: int


@dataclass(frozen=True)
class SkillDepth:
    """Where a skill is supported and for how long, as an ATS parser would count it."""

    skill_id: str
    months: int
    last_used: date | None
    experience_ids: tuple[str, ...]
    statement_ids: tuple[str, ...]
    in_skills_section: bool


@dataclass(frozen=True)
class ProfileIndex:
    master_resume_id: str
    statements: tuple[ProfileStatement, ...]
    # Technologies each role may truthfully name: its statements plus its stack.
    experience_skill_ids: dict[str, frozenset[str]]
    experience_technology_names: dict[str, tuple[str, ...]]
    skills: dict[str, SkillDepth]
    # Normalized names of every listed skill and stack item, for vacancy skills
    # that are not in the dictionary.
    named_skills: dict[str, str]
    total_months: int
    dictionary_version: str
    _by_experience: dict[str, tuple[ProfileStatement, ...]] = field(default_factory=dict)

    def statements_for(self, experience_id: str) -> tuple[ProfileStatement, ...]:
        return self._by_experience.get(experience_id, ())

    def statement(self, statement_id: str) -> ProfileStatement | None:
        return next((item for item in self.statements if item.id == statement_id), None)

    @property
    def skill_ids(self) -> frozenset[str]:
        return frozenset(self.skills)

    def knows(self, skill_id: str | None, surface_form: str) -> bool:
        if skill_id is not None:
            return skill_id in self.skills
        return alias_key(surface_form) in self.named_skills


def parse_profile_date(value: str, *, end: bool = False) -> date | None:
    """Parse a profile date at month precision; a bare year covers the whole year."""
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    if not text:
        return None
    if match := re.fullmatch(r"(\d{4})", text):
        return date(int(match[1]), 12 if end else 1, 1)
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", text):
        return _month_date(int(match[1]), int(match[2]))
    if match := re.fullmatch(r"(\d{1,2})[/.](\d{4})", text):
        return _month_date(int(match[2]), int(match[1]))
    if match := re.fullmatch(r"\d{1,2}\.(\d{1,2})\.(\d{4})", text):
        return _month_date(int(match[2]), int(match[1]))
    if match := re.fullmatch(r"([^\W\d_]+)\.?,? (\d{4})", text):
        month = _MONTHS.get(match[1])
        return _month_date(int(match[2]), month) if month else None
    return None


def _month_date(year: int, month: int) -> date | None:
    try:
        return date(year, month, 1)
    except ValueError:
        return None


def _month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


def experience_months(experience: MasterExperience, *, today: date) -> set[int]:
    """Calendar months covered by a role; empty when its dates cannot be read."""
    start = parse_profile_date(experience.start_date)
    end = (
        date(today.year, today.month, 1)
        if experience.is_current
        else parse_profile_date(experience.end_date, end=True)
    )
    if start is None:
        return set()
    if end is None or end < start:
        end = start
    return set(range(_month_index(start), _month_index(end) + 1))


def split_statement_texts(text: str) -> list[str]:
    """Split a bullet that holds several list items into its items."""
    parts = [part.strip() for part in _LIST_MARKER.split(text) if part.strip()]
    return parts or [text.strip()]


def build_profile_index(
    master: MasterResume,
    *,
    dictionary: SkillDictionary | None = None,
    today: date | None = None,
) -> ProfileIndex:
    dictionary = dictionary or default_skill_dictionary()
    reference = today or datetime.now(UTC).date()
    statements: list[ProfileStatement] = []
    by_experience: dict[str, tuple[ProfileStatement, ...]] = {}
    experience_skills: dict[str, frozenset[str]] = {}
    experience_technologies: dict[str, tuple[str, ...]] = {}
    months_by_skill: dict[str, set[int]] = {}
    last_used: dict[str, date] = {}
    experiences_by_skill: dict[str, list[str]] = {}
    statements_by_skill: dict[str, list[str]] = {}
    named: dict[str, str] = {}
    all_months: set[int] = set()

    for skill in master.skills:
        named.setdefault(alias_key(skill.name), skill.name)

    order = 0
    for experience in master.experiences:
        role_statements: list[ProfileStatement] = []
        for bullet in experience.bullets:
            texts = split_statement_texts(bullet.text)
            for index, text in enumerate(texts, start=1):
                statement_id = bullet.id if len(texts) == 1 else f"{bullet.id}-p{index}"
                skill_ids = frozenset(mention.skill_id for mention in dictionary.scan(text))
                role_statements.append(
                    ProfileStatement(
                        id=statement_id,
                        experience_id=experience.id,
                        source_bullet_id=bullet.id,
                        text=text,
                        evidence_ids=tuple(bullet.evidence_ids),
                        skill_ids=skill_ids,
                        has_metric=bool(_NUMBER.search(text)),
                        order=order,
                    )
                )
                order += 1
        technologies = [item.technology for item in experience.stack if item.technology.strip()]
        detail_text = "\n".join(
            [
                *(f"{item.technology} {item.context}" for item in experience.stack),
                *(
                    f"{item.responsibility} {item.decisions}"
                    for item in experience.responsibilities
                ),
                *(
                    f"{item.name} {item.description} {item.systems}"
                    for item in experience.projects
                ),
            ]
        )
        role_skill_ids: set[str] = {
            skill_id for statement in role_statements for skill_id in statement.skill_ids
        }
        role_skill_ids.update(mention.skill_id for mention in dictionary.scan(detail_text))
        for technology in technologies:
            named.setdefault(alias_key(technology), technology)
            if resolved := dictionary.lookup(technology):
                role_skill_ids.add(resolved)

        covered = experience_months(experience, today=reference)
        all_months |= covered
        role_end = max(covered) if covered else None
        for skill_id in role_skill_ids:
            months_by_skill.setdefault(skill_id, set()).update(covered)
            experiences_by_skill.setdefault(skill_id, []).append(experience.id)
            if role_end is not None:
                used = date(role_end // 12, role_end % 12 + 1, 1)
                if skill_id not in last_used or used > last_used[skill_id]:
                    last_used[skill_id] = used
        for statement in role_statements:
            for skill_id in statement.skill_ids:
                statements_by_skill.setdefault(skill_id, []).append(statement.id)

        statements.extend(role_statements)
        by_experience[experience.id] = tuple(role_statements)
        experience_skills[experience.id] = frozenset(role_skill_ids)
        experience_technologies[experience.id] = tuple(dict.fromkeys(technologies))

    listed_skill_ids = {
        resolved for skill in master.skills if (resolved := dictionary.lookup(skill.name))
    }
    project_text = "\n".join(
        bullet.text for project in master.projects for bullet in project.bullets
    )
    project_skill_ids = {mention.skill_id for mention in dictionary.scan(project_text)}
    skills = {
        skill_id: SkillDepth(
            skill_id=skill_id,
            months=len(months_by_skill.get(skill_id, ())),
            last_used=last_used.get(skill_id),
            experience_ids=tuple(experiences_by_skill.get(skill_id, ())),
            statement_ids=tuple(statements_by_skill.get(skill_id, ())),
            in_skills_section=skill_id in listed_skill_ids,
        )
        for skill_id in sorted({*months_by_skill, *listed_skill_ids, *project_skill_ids})
    }
    return ProfileIndex(
        master_resume_id=master.id,
        statements=tuple(statements),
        experience_skill_ids=experience_skills,
        experience_technology_names=experience_technologies,
        skills=skills,
        named_skills=named,
        total_months=len(all_months),
        dictionary_version=dictionary.version,
        _by_experience=by_experience,
    )


__all__ = [
    "ProfileIndex",
    "ProfileStatement",
    "SkillDepth",
    "build_profile_index",
    "experience_months",
    "parse_profile_date",
    "split_statement_texts",
]
