"""Canonical skill dictionary and deterministic skill mention scanning."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_SKILL_DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "ats_skills.json"
SUPPORTED_ALIAS_LANGUAGES = ("en", "de", "fr")

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_SEPARATOR_RUN = re.compile(r"[\s\-_]+")
_ALIAS_PART_SPLIT = re.compile(r"[\s\-]+")
# Characters that continue a technology token: "C" in "C++", "Java" in "JavaScript".
_LEFT_BOUNDARY = r"(?<!\w)"
_RIGHT_BOUNDARY = r"(?![\w+#])"


class SkillDictionaryError(ValueError):
    pass


@dataclass(frozen=True)
class SkillEntry:
    id: str
    label: str
    category: str
    aliases: tuple[str, ...]
    case_sensitive_aliases: tuple[str, ...]
    ambiguous_aliases: tuple[str, ...]

    @property
    def all_aliases(self) -> tuple[str, ...]:
        return (
            (self.label,) + self.aliases + self.case_sensitive_aliases + self.ambiguous_aliases
        )


@dataclass(frozen=True)
class SkillMention:
    """A dictionary hit. Offsets refer to `normalize_text(text)`."""

    skill_id: str
    surface_form: str
    start: int
    end: int
    ambiguous: bool


def normalize_text(text: str) -> str:
    """Unicode-normalize text without changing case, so surface forms stay exact."""

    normalized = unicodedata.normalize("NFKC", text).translate(_DASHES)
    return normalized.replace("­", "")


def alias_key(value: str) -> str:
    """Case- and separator-insensitive key: 'Spring-Boot' == 'spring boot'."""

    text = normalize_text(value).strip().rstrip(",;:!?.").strip()
    return _SEPARATOR_RUN.sub(" ", text).casefold()


def exact_key(value: str) -> str:
    """Separator-insensitive but case-preserving key for case-sensitive aliases."""

    text = normalize_text(value).strip().rstrip(",;:!?.").strip()
    return _SEPARATOR_RUN.sub(" ", text)


def _insensitive_aliases(entry: SkillEntry) -> tuple[str, ...]:
    """The label counts as a case-insensitive alias unless it is listed as a special one."""

    special = {exact_key(alias) for alias in entry.case_sensitive_aliases + entry.ambiguous_aliases}
    label = () if exact_key(entry.label) in special else (entry.label,)
    return label + tuple(alias for alias in entry.aliases if alias != entry.label)


def _alias_pattern(alias: str) -> str:
    parts = [re.escape(part) for part in _ALIAS_PART_SPLIT.split(alias.strip()) if part]
    return r"[\s\-]+".join(parts)


class SkillDictionary:
    def __init__(self, *, version: str, entries: tuple[SkillEntry, ...]) -> None:
        self.version = version
        self.entries: Mapping[str, SkillEntry] = {entry.id: entry for entry in entries}
        self._insensitive: dict[str, str] = {}
        self._sensitive: dict[str, str] = {}
        self._ambiguous: dict[str, str] = {}
        seen: dict[str, str] = {}
        for entry in entries:
            groups = (
                (_insensitive_aliases(entry), self._insensitive, alias_key),
                (entry.case_sensitive_aliases, self._sensitive, exact_key),
                (entry.ambiguous_aliases, self._ambiguous, exact_key),
            )
            for aliases, target, key_function in groups:
                for alias in aliases:
                    collision_key = alias_key(alias)
                    owner = seen.get(collision_key)
                    if owner is not None and owner != entry.id:
                        raise SkillDictionaryError(
                            f"Alias {alias!r} of {entry.id!r} collides with {owner!r}"
                        )
                    seen[collision_key] = entry.id
                    target[key_function(alias)] = entry.id
        self._free_text_pattern = self._compile(include_ambiguous=False)
        self._phrase_pattern = self._compile(include_ambiguous=True)

    def _compile(self, *, include_ambiguous: bool) -> re.Pattern[str]:
        alternatives: list[tuple[int, str]] = []
        for entry in self.entries.values():
            for alias in _insensitive_aliases(entry):
                alternatives.append((len(alias), _alias_pattern(alias)))
            exact_aliases = entry.case_sensitive_aliases
            if include_ambiguous:
                exact_aliases += entry.ambiguous_aliases
            for alias in exact_aliases:
                alternatives.append((len(alias), f"(?-i:{_alias_pattern(alias)})"))
        # Longest first, so "JavaScript" wins over "Java" and "ASP.NET" over ".NET".
        ordered = sorted(set(alternatives), key=lambda item: (-item[0], item[1]))
        body = "|".join(pattern for _, pattern in ordered)
        return re.compile(f"{_LEFT_BOUNDARY}(?:{body}){_RIGHT_BOUNDARY}", re.IGNORECASE)

    def get(self, skill_id: str) -> SkillEntry | None:
        return self.entries.get(skill_id)

    def label(self, skill_id: str) -> str:
        entry = self.entries.get(skill_id)
        return entry.label if entry else skill_id

    def lookup(self, phrase: str) -> str | None:
        """Resolve a whole skill phrase, including ambiguous aliases like 'Go' or 'R'."""

        exact = exact_key(phrase)
        return (
            self._sensitive.get(exact)
            or self._ambiguous.get(exact)
            or self._insensitive.get(alias_key(phrase))
        )

    def _resolve_match(self, surface: str) -> tuple[str, bool] | None:
        exact = exact_key(surface)
        if exact in self._sensitive:
            return self._sensitive[exact], False
        if exact in self._ambiguous:
            return self._ambiguous[exact], True
        skill_id = self._insensitive.get(alias_key(surface))
        return (skill_id, False) if skill_id else None

    def scan(self, text: str, *, include_ambiguous: bool = False) -> list[SkillMention]:
        """Find non-overlapping skill mentions, longest alias first.

        Free text should be scanned without ambiguous aliases. A short phrase that is
        already known to name a skill (for example a model-extracted "C/C++") can be
        scanned with them.
        """

        pattern = self._phrase_pattern if include_ambiguous else self._free_text_pattern
        normalized = normalize_text(text)
        mentions: list[SkillMention] = []
        for match in pattern.finditer(normalized):
            resolved = self._resolve_match(match.group(0))
            if resolved is None:
                continue
            skill_id, ambiguous = resolved
            mentions.append(
                SkillMention(
                    skill_id=skill_id,
                    surface_form=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    ambiguous=ambiguous,
                )
            )
        return mentions

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> SkillDictionary:
        if data.get("schemaVersion") != 1:
            raise SkillDictionaryError("Unsupported skill dictionary schema version")
        version = data.get("version")
        if not isinstance(version, str) or not version.strip():
            raise SkillDictionaryError("Skill dictionary version is required")
        raw_skills = data.get("skills")
        if not isinstance(raw_skills, list) or not raw_skills:
            raise SkillDictionaryError("Skill dictionary must contain skills")
        entries: list[SkillEntry] = []
        ids: set[str] = set()
        for raw in raw_skills:
            entry = _parse_entry(raw)
            if entry.id in ids:
                raise SkillDictionaryError(f"Duplicate skill id {entry.id!r}")
            ids.add(entry.id)
            entries.append(entry)
        return cls(version=version.strip(), entries=tuple(entries))


def _string_list(value: Any, *, field: str, skill_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SkillDictionaryError(f"{field} of {skill_id!r} must be a list of strings")
    items = tuple(item.strip() for item in value)
    for item in items:
        if not item or item.endswith((".", ",", ";", ":")):
            raise SkillDictionaryError(f"Invalid alias {item!r} in {field} of {skill_id!r}")
    return items


def _parse_entry(raw: Any) -> SkillEntry:
    if not isinstance(raw, Mapping):
        raise SkillDictionaryError("Skill entries must be objects")
    skill_id = raw.get("id")
    if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", skill_id):
        raise SkillDictionaryError(f"Invalid skill id {skill_id!r}")
    label = raw.get("label")
    category = raw.get("category")
    if not isinstance(label, str) or not label.strip():
        raise SkillDictionaryError(f"Skill {skill_id!r} needs a label")
    if not isinstance(category, str) or not category.strip():
        raise SkillDictionaryError(f"Skill {skill_id!r} needs a category")
    alias_groups = raw.get("aliases")
    if not isinstance(alias_groups, Mapping) or set(alias_groups) != set(
        SUPPORTED_ALIAS_LANGUAGES
    ):
        raise SkillDictionaryError(f"Skill {skill_id!r} needs en/de/fr alias lists")
    aliases: list[str] = []
    for language in SUPPORTED_ALIAS_LANGUAGES:
        for alias in _string_list(
            alias_groups[language], field=f"aliases.{language}", skill_id=skill_id
        ):
            if alias not in aliases:
                aliases.append(alias)
    return SkillEntry(
        id=skill_id,
        label=label.strip(),
        category=category.strip(),
        aliases=tuple(aliases),
        case_sensitive_aliases=_string_list(
            raw.get("caseSensitiveAliases", []), field="caseSensitiveAliases", skill_id=skill_id
        ),
        ambiguous_aliases=_string_list(
            raw.get("ambiguousAliases", []), field="ambiguousAliases", skill_id=skill_id
        ),
    )


def load_skill_dictionary(path: Path | None = None) -> SkillDictionary:
    if path is None:
        return default_skill_dictionary()
    return SkillDictionary.from_data(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_skill_dictionary() -> SkillDictionary:
    data = json.loads(DEFAULT_SKILL_DICTIONARY_PATH.read_text(encoding="utf-8"))
    return SkillDictionary.from_data(data)
