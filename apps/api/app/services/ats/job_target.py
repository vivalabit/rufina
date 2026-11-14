"""Vacancy parsing into a `JobTarget`.

The model reads the posting once and returns a `JobTargetDraft`. Everything after that is
deterministic: surface forms are checked against the posting text, skills are mapped to the
dictionary, frequencies are counted, and title, seniority and language are normalized.
Without a model, `extract_job_target_without_model` builds a target from the dictionary
and section headings alone.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.services.ai_backend import AIBackend, AIBackendError, AIRequest, generate_with_retries
from app.services.ats.models import (
    CefrLevel,
    JobKnockout,
    JobSkill,
    JobTarget,
    JobTargetDraft,
    PostingLanguage,
    Seniority,
    SkillImportance,
    SkillSource,
)
from app.services.ats.skill_dictionary import (
    SkillDictionary,
    SkillMention,
    alias_key,
    default_skill_dictionary,
    normalize_text,
)

EXTRACTOR_VERSION = "job-target-v2"
MAX_PROMPT_POSTING_CHARS = 20_000
MAX_SKILL_SURFACE_CHARS = 80
MAX_SKILL_SURFACE_WORDS = 6
MAX_RESPONSIBILITIES = 12
MAX_REQUIREMENT_CHARS = 300


class JobTargetExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VacancyInput:
    title: str
    description: str

    @property
    def text(self) -> str:
        return f"{self.title.strip()}\n\n{self.description.strip()}".strip()

    @classmethod
    def from_job_data(cls, data: Mapping[str, Any]) -> VacancyInput:
        """Build input from a stored job payload (`stored_jobs.data` style keys)."""

        title = data.get("title")
        full = data.get("fullDescription") or data.get("full_description")
        if isinstance(full, str) and full.strip():
            return cls(title=title if isinstance(title, str) else "", description=full)
        parts: list[str] = []
        for key in ("description", "overview", "responsibilities", "requirements", "skills"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, list):
                items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
                parts.extend(f"- {item}" for item in items)
        return cls(title=title if isinstance(title, str) else "", description="\n".join(parts))


# ---------------------------------------------------------------------------
# Caching


class JobTargetCache(Protocol):
    def get(self, key: str) -> JobTarget | None: ...

    def put(self, key: str, target: JobTarget) -> None: ...


@dataclass
class InMemoryJobTargetCache:
    items: dict[str, JobTarget] = field(default_factory=dict)

    def get(self, key: str) -> JobTarget | None:
        return self.items.get(key)

    def put(self, key: str, target: JobTarget) -> None:
        self.items[key] = target


@dataclass(frozen=True)
class JsonDirectoryJobTargetCache:
    """One JSON file per key. Used by local tooling (eval and baseline scripts)."""

    directory: Path

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("cache keys must be sha256 hex digests")
        return self.directory / f"{key}.json"

    def get(self, key: str) -> JobTarget | None:
        try:
            return JobTarget.model_validate_json(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, target: JobTarget) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = target.model_dump_json(by_alias=True, indent=2)
        handle, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temporary, self._path(key))
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def source_sha256(vacancy: VacancyInput) -> str:
    return hashlib.sha256(normalize_text(vacancy.text).encode("utf-8")).hexdigest()


def job_target_cache_key(vacancy: VacancyInput, *, dictionary_version: str, mode: str) -> str:
    """Key = posting content + extractor version + dictionary version + extraction mode."""

    material = json.dumps(
        [EXTRACTOR_VERSION, dictionary_version, mode, source_sha256(vacancy)],
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Model call

_PROMPT = """You extract a structured target from one job posting for ATS resume tailoring.

Rules:
- Use only the posting text. Never add requirements that are not written there.
- skills: every technology, tool, platform, method, certification or domain skill the
  candidate is asked to have or will work with. One entry per skill. Copy surface_form
  exactly as written in the posting (same spelling and casing) and keep it short: the
  name of the skill only, for example "Python", not "solid Python knowledge".
  importance is "required" unless the posting marks the skill as optional (nice to have,
  a plus, von Vorteil, wünschenswert, idealerweise, un atout, un plus).
  min_years: years of experience asked for that specific skill, otherwise null.
  Do not list spoken languages (they are knockouts) or generic soft skills.
- knockouts: requirements that can disqualify a candidate: work permit or nationality,
  spoken language level, location or on-site presence, required degree, minimum total
  years of experience, mandatory certification. requirement is a short quote.
  language is the ISO 639-1 code for language knockouts, otherwise null. cefr_level is
  A1-C2 when stated; map fluent, fliessend, verhandlungssicher, courant to "C1" and
  native, Muttersprache, langue maternelle to "native"; otherwise null. years is the
  minimum number of years for experience knockouts, otherwise null.
- responsibilities: up to 12 main tasks of the role, short, in the posting's language.
- title: the job title as written, without gender markers or workload percentages.
- seniority: one of intern, junior, mid, senior, lead, unknown.
- language: the language the posting is written in (de, en, fr, it or unknown).

Return only JSON that matches this JSON schema:
{schema}

Posting:
<<<
{posting}
>>>
"""


def build_job_target_prompt(vacancy: VacancyInput) -> str:
    schema = json.dumps(JobTargetDraft.model_json_schema(), separators=(",", ":"))
    posting = normalize_text(vacancy.text)[:MAX_PROMPT_POSTING_CHARS]
    return _PROMPT.format(schema=schema, posting=posting)


def _parse_draft(data: Any) -> JobTargetDraft:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    if isinstance(data, Mapping) and isinstance(data.get("jobTarget"), Mapping):
        data = data["jobTarget"]
    try:
        return JobTargetDraft.model_validate(data)
    except ValidationError as exc:
        raise JobTargetExtractionError("Vacancy parsing returned an invalid structure") from exc


class JobTargetExtractor:
    def __init__(
        self,
        backend: AIBackend | None,
        *,
        dictionary: SkillDictionary | None = None,
        cache: JobTargetCache | None = None,
        model: str = "",
        agent_id: str = "",
        thinking: str = "off",
        timeout_seconds: int = 90,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 1.0,
        fallback_to_dictionary: bool = False,
    ) -> None:
        self.backend = backend
        self.dictionary = dictionary or default_skill_dictionary()
        self.cache = cache
        self.model = model
        self.agent_id = agent_id
        self.thinking = thinking
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.fallback_to_dictionary = fallback_to_dictionary

    @property
    def mode(self) -> str:
        if self.backend is None:
            return "dictionary"
        return f"{self.backend.name}:{self.model or 'default'}"

    def extract(self, vacancy: VacancyInput) -> JobTarget:
        key = job_target_cache_key(
            vacancy, dictionary_version=self.dictionary.version, mode=self.mode
        )
        if self.cache is not None and (cached := self.cache.get(key)) is not None:
            return cached
        if self.backend is None:
            target = extract_job_target_without_model(vacancy, dictionary=self.dictionary)
        else:
            try:
                draft, model_name = self._request_draft(self.backend, vacancy)
            except JobTargetExtractionError:
                if not self.fallback_to_dictionary:
                    raise
                # Not cached under the model key, so the next call retries the model.
                return extract_job_target_without_model(vacancy, dictionary=self.dictionary)
            target = normalize_job_target(
                draft, vacancy, dictionary=self.dictionary, model=model_name
            )
        if self.cache is not None:
            self.cache.put(key, target)
        return target

    def _request_draft(
        self, backend: AIBackend, vacancy: VacancyInput
    ) -> tuple[JobTargetDraft, str]:
        request = AIRequest(
            prompt=build_job_target_prompt(vacancy),
            model=self.model,
            agent_id=self.agent_id,
            thinking=self.thinking,
            timeout_seconds=self.timeout_seconds,
            structured=True,
            response_model=JobTargetDraft,
        )
        try:
            result = generate_with_retries(
                backend,
                request,
                max_attempts=self.max_attempts,
                retry_backoff_seconds=self.retry_backoff_seconds,
            )
        except AIBackendError as exc:
            raise JobTargetExtractionError(f"Vacancy parsing failed ({exc.code})") from exc
        return _parse_draft(result.structured_data), result.model


# ---------------------------------------------------------------------------
# Deterministic normalization


@dataclass
class _SkillAccumulator:
    canonical_id: str | None
    label: str
    surfaces: Counter[str]
    first_position: int
    frequency: int
    importance: SkillImportance
    min_years: int | None
    source: SkillSource

    def merge(self, importance: SkillImportance, min_years: int | None) -> None:
        if importance == "required":
            self.importance = "required"
        if min_years is not None:
            self.min_years = max(self.min_years or 0, min_years)

    def build(self) -> JobSkill:
        surface = self.surfaces.most_common(1)[0][0]
        return JobSkill(
            canonical_id=self.canonical_id,
            label=self.label[:120],
            surface_form=surface[:MAX_SKILL_SURFACE_CHARS],
            importance=self.importance,
            frequency=self.frequency,
            min_years=self.min_years,
            source=self.source,
        )


def _occurrence_surfaces(occurrences: list[tuple[int, str]]) -> Counter[str]:
    # Insertion order = text order, so most_common breaks ties by first occurrence.
    return Counter(surface for _, surface in sorted(occurrences))


def normalize_job_target(
    draft: JobTargetDraft | None,
    vacancy: VacancyInput,
    *,
    dictionary: SkillDictionary | None = None,
    model: str = "",
) -> JobTarget:
    dictionary = dictionary or default_skill_dictionary()
    text = normalize_text(vacancy.text)
    sections = _Sections(text)
    mentions_by_id: dict[str, list[SkillMention]] = {}
    for mention in dictionary.scan(text, include_ambiguous=True):
        mentions_by_id.setdefault(mention.skill_id, []).append(mention)

    skills: dict[str, _SkillAccumulator] = {}

    def add(
        key: str,
        *,
        canonical_id: str | None,
        label: str,
        occurrences: list[tuple[int, str]],
        importance: SkillImportance,
        min_years: int | None,
        source: SkillSource,
    ) -> None:
        if key in skills:
            skills[key].merge(importance, min_years)
            return
        skills[key] = _SkillAccumulator(
            canonical_id=canonical_id,
            label=label,
            surfaces=_occurrence_surfaces(occurrences),
            first_position=min(position for position, _ in occurrences),
            frequency=len(occurrences),
            importance=importance,
            min_years=min_years,
            source=source,
        )

    for item in draft.skills if draft else ():
        surface = _clean_phrase(item.surface_form)
        if not surface or len(surface) > MAX_SKILL_SURFACE_CHARS:
            continue
        if len(surface.split()) > MAX_SKILL_SURFACE_WORDS:
            continue
        min_years = item.min_years if item.min_years and 1 <= item.min_years <= 30 else None
        skill_ids = _phrase_skill_ids(dictionary, surface)
        if skill_ids:
            for skill_id in skill_ids:
                # The model named this skill, so ambiguous aliases ("Go", "R") count here.
                occurrences = [(m.start, m.surface_form) for m in mentions_by_id.get(skill_id, [])]
                if occurrences:
                    add(
                        skill_id,
                        canonical_id=skill_id,
                        label=dictionary.label(skill_id),
                        occurrences=occurrences,
                        importance=item.importance,
                        min_years=min_years,
                        source="model",
                    )
            continue
        occurrences = _find_phrase(text, surface)
        if occurrences:
            add(
                f"raw:{alias_key(surface)}",
                canonical_id=None,
                label=surface,
                occurrences=occurrences,
                importance=item.importance,
                min_years=min_years,
                source="model",
            )

    for skill_id, mentions in mentions_by_id.items():
        if skill_id in skills:
            continue
        unambiguous = [mention for mention in mentions if not mention.ambiguous]
        if not unambiguous:
            continue
        importance: SkillImportance = (
            "required"
            if any(sections.is_required_at(mention.start) for mention in unambiguous)
            else "preferred"
        )
        add(
            skill_id,
            canonical_id=skill_id,
            label=dictionary.label(skill_id),
            occurrences=[(mention.start, mention.surface_form) for mention in unambiguous],
            importance=importance,
            min_years=None,
            source="dictionary",
        )

    ordered = sorted(
        skills.values(),
        key=lambda acc: (acc.importance != "required", -acc.frequency, acc.first_position),
    )
    title = vacancy.title.strip() or (draft.title.strip() if draft else "")
    if draft is not None:
        knockouts = _normalize_knockouts(draft)
        responsibilities = _normalize_responsibilities(draft.responsibilities)
    else:
        knockouts = _detect_experience_knockouts(text)
        responsibilities = _normalize_responsibilities(sections.responsibility_lines())
    return JobTarget(
        title=title[:300],
        normalized_title=normalize_title(title)[:300],
        seniority=_resolve_seniority(title, draft.seniority if draft else "unknown"),
        language=detect_posting_language(text) or (draft.language if draft else "unknown"),
        knockouts=knockouts,
        responsibilities=responsibilities,
        skills=tuple(acc.build() for acc in ordered),
        extractor_version=EXTRACTOR_VERSION,
        dictionary_version=dictionary.version,
        source_sha256=source_sha256(vacancy),
        model=model,
    )


def extract_job_target_without_model(
    vacancy: VacancyInput, *, dictionary: SkillDictionary | None = None
) -> JobTarget:
    """Dictionary-only target: importance from section headings, no unmapped skills."""

    return normalize_job_target(None, vacancy, dictionary=dictionary)


def _phrase_skill_ids(dictionary: SkillDictionary, phrase: str) -> list[str]:
    skill_id = dictionary.lookup(phrase)
    if skill_id:
        return [skill_id]
    ids: list[str] = []
    for mention in dictionary.scan(phrase, include_ambiguous=True):
        if mention.skill_id not in ids:
            ids.append(mention.skill_id)
    return ids


def _find_phrase(text: str, phrase: str) -> list[tuple[int, str]]:
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", phrase) if part]
    if not parts:
        return []
    pattern = re.compile(r"(?<!\w)" + r"[\s\-]+".join(parts) + r"(?![\w+#])", re.IGNORECASE)
    return [(match.start(), match.group(0)) for match in pattern.finditer(text)]


_PHRASE_TRIM = " \t\r\n\"'`*•·-–—,;:!?()[]"


def _clean_phrase(value: str) -> str:
    text = re.sub(r"\s+", " ", normalize_text(value)).strip(_PHRASE_TRIM)
    return text.rstrip(".").strip()


# ---------------------------------------------------------------------------
# Title, seniority and language

_GENDER_MARKERS = re.compile(
    r"\(\s*(?:[a-z]{1,3}\s*[/|,]\s*)+[a-z]{1,3}\s*\)"
    r"|\(\s*(?:all genders|alle geschlechter|gn\*?)\s*\)"
    r"|(?<!\w)[mwfdhx](?:\s*/\s*[mwfdhx]){1,3}(?!\w)",
    re.IGNORECASE,
)
_WORKLOAD = re.compile(
    r"\d{1,3}\s*%?\s*(?:-|bis|to|à)\s*\d{1,3}\s*%|\d{1,3}\s*%", re.IGNORECASE
)


def clean_title(title: str) -> str:
    """The posting title without gender markers and workload, in its original case."""
    text = normalize_text(title)
    text = _GENDER_MARKERS.sub(" ", text)
    text = _WORKLOAD.sub(" ", text)
    text = re.sub(r"(?<=[^\W\d_])[:*]in(?:nen)?\b", "", text)
    text = re.sub(r"\(\s*\)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -|,/·:")


def normalize_title(title: str) -> str:
    return clean_title(title).casefold()


_SENIORITY_TITLE_WORDS: tuple[tuple[Seniority, frozenset[str]], ...] = (
    (
        "intern",
        frozenset({
            "intern", "internship", "praktikum", "praktikant", "praktikantin", "trainee",
            "werkstudent", "werkstudentin", "stagiaire", "lernende", "lernender",
            "lehrstelle", "lehrling", "apprenti", "apprentie",
        }),
    ),
    (
        "lead",
        frozenset({
            "lead", "principal", "staff", "head", "director", "chief", "leiter", "leiterin",
            "teamleiter", "teamleiterin", "teamlead", "techlead",
        }),
    ),
    ("senior", frozenset({"senior", "sr"})),
    (
        "junior",
        frozenset({
            "junior", "jr", "graduate", "einsteiger", "berufseinsteiger",
            "berufseinsteigerin", "débutant", "débutante",
        }),
    ),
    ("mid", frozenset({"mid", "intermediate"})),
)


def title_seniority(title: str) -> Seniority | None:
    words = set(re.findall(r"[^\W\d_]+", normalize_title(title)))
    for level, keywords in _SENIORITY_TITLE_WORDS:
        if words & keywords:
            return level
    return None


def _resolve_seniority(title: str, drafted: Seniority) -> Seniority:
    """An explicit title keyword wins; otherwise trust the model."""

    return title_seniority(title) or drafted


_STOPWORDS: dict[PostingLanguage, frozenset[str]] = {
    "de": frozenset({
        "der", "die", "das", "und", "mit", "für", "wir", "sie", "ihr", "ihre", "sind", "ist",
        "von", "zu", "auf", "bei", "im", "ein", "eine", "oder", "als", "auch", "du", "dein",
        "deine", "unsere", "unser", "wird", "werden",
    }),
    "en": frozenset({
        "the", "and", "with", "for", "you", "your", "we", "our", "are", "is", "of", "to", "on",
        "at", "an", "or", "as", "will", "be", "this", "that", "have",
    }),
    "fr": frozenset({
        "et", "avec", "pour", "vous", "votre", "vos", "nous", "nos", "sont", "est", "des", "du",
        "une", "ou", "au", "aux", "dans", "sur", "les",
    }),
    "it": frozenset({
        "il", "lo", "gli", "con", "per", "voi", "vostro", "noi", "nostri", "sono", "è", "di",
        "del", "della", "delle", "una", "nel", "che",
    }),
}


def detect_posting_language(text: str) -> PostingLanguage | None:
    """Stopword vote; None when the text is short or mixed."""

    tokens = re.findall(r"[^\W\d_]+", text.casefold())
    counts = Counter(
        language for token in tokens for language, words in _STOPWORDS.items() if token in words
    )
    ranked = counts.most_common(2)
    if not ranked or ranked[0][1] < 5:
        return None
    if len(ranked) > 1 and ranked[0][1] < 1.5 * ranked[1][1]:
        return None
    return ranked[0][0]


# ---------------------------------------------------------------------------
# Knockouts and responsibilities

_LANGUAGE_NAMES: dict[str, frozenset[str]] = {
    "de": frozenset({"deutsch", "german", "allemand", "tedesco", "deutschkenntnisse"}),
    "en": frozenset({"englisch", "english", "anglais", "inglese", "englischkenntnisse"}),
    "fr": frozenset({"französisch", "franzoesisch", "french", "français", "francais",
                     "francese", "französischkenntnisse"}),
    "it": frozenset({"italienisch", "italian", "italien", "italiano"}),
}
_NATIVE_WORDS = frozenset(
    {"native", "muttersprache", "mother tongue", "langue maternelle", "madrelingua"}
)
_CEFR_LEVELS = frozenset({"A1", "A2", "B1", "B2", "C1", "C2"})
_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?"
    r"(?:jahre|jahren|years|year|yrs|ans|années|anni)\b",
    re.IGNORECASE,
)


def _language_code(value: str | None, requirement: str) -> str | None:
    if value:
        lowered = value.strip().casefold()
        if lowered in _LANGUAGE_NAMES:
            return lowered
        for code, names in _LANGUAGE_NAMES.items():
            if lowered in names:
                return code
    words = set(re.findall(r"[^\W\d_]+", requirement.casefold()))
    found = [code for code, names in _LANGUAGE_NAMES.items() if words & names]
    return found[0] if len(found) == 1 else None


def _cefr(value: str | None) -> CefrLevel | None:
    if not value:
        return None
    if value.strip().casefold() in _NATIVE_WORDS:
        return "native"
    match = re.search(r"\b([ABC][12])\b", value.upper())
    return match.group(1) if match and match.group(1) in _CEFR_LEVELS else None  # type: ignore[return-value]


def _truncate(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", normalize_text(value)).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")


def _normalize_knockouts(draft: JobTargetDraft) -> tuple[JobKnockout, ...]:
    knockouts: list[JobKnockout] = []
    seen: set[tuple[str, str | None, str]] = set()
    for item in draft.knockouts:
        requirement = _truncate(item.requirement, MAX_REQUIREMENT_CHARS)
        if not requirement:
            continue
        language = (
            _language_code(item.language, requirement) if item.kind == "language" else None
        )
        years = item.years if item.years and 1 <= item.years <= 40 else None
        if item.kind == "experience" and years is None:
            match = _YEARS.search(requirement)
            years = int(match.group(1)) if match and 1 <= int(match.group(1)) <= 40 else None
        key = (item.kind, language, alias_key(requirement))
        if key in seen:
            continue
        seen.add(key)
        knockouts.append(
            JobKnockout(
                kind=item.kind,
                requirement=requirement,
                language=language,
                cefr_level=_cefr(item.cefr_level) if item.kind == "language" else None,
                years=years,
            )
        )
    return tuple(knockouts)


def _detect_experience_knockouts(text: str) -> tuple[JobKnockout, ...]:
    for line in text.splitlines():
        match = _YEARS.search(line)
        if match and 1 <= int(match.group(1)) <= 40:
            return (
                JobKnockout(
                    kind="experience",
                    requirement=_truncate(_clean_phrase(line), MAX_REQUIREMENT_CHARS),
                    years=int(match.group(1)),
                ),
            )
    return ()


def _normalize_responsibilities(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _truncate(_clean_phrase(item), MAX_REQUIREMENT_CHARS)
        if len(text) < 3 or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
        if len(result) >= MAX_RESPONSIBILITIES:
            break
    return tuple(result)


# ---------------------------------------------------------------------------
# Section headings (used for dictionary-only importance and responsibilities)

_HEADING_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "preferred",
        re.compile(
            r"nice[\s\-]to[\s\-]have|von vorteil|wünschenswert|ein plus|bonus|"
            r"un atout|un plus|souhaité|optional",
            re.IGNORECASE,
        ),
    ),
    (
        "responsibilities",
        re.compile(
            r"aufgaben|tätigkeiten|verantwortlichkeiten|responsibilities|your tasks|"
            r"your role|what you will do|what you'll do|vos tâches|vos missions|missions|"
            r"tâches|deine rolle|ihre rolle",
            re.IGNORECASE,
        ),
    ),
    (
        "requirements",
        re.compile(
            r"anforderungen|profil|qualifikation|requirements|qualifications|"
            r"what you bring|who you are|must have|must-have|voraussetzungen|"
            r"das bringst du mit|das bringen sie mit|votre profil|compétences requises|"
            # Section labels of `build_full_vacancy_description`.
            r"^skills$",
            re.IGNORECASE,
        ),
    ),
    (
        "other",
        re.compile(
            r"wir bieten|was wir bieten|benefits|we offer|what we offer|nous offrons|"
            r"über uns|about us|à propos|kontakt|contact|^company$",
            re.IGNORECASE,
        ),
    ),
)
_OPTIONAL_LINE = re.compile(
    r"nice[\s\-]to[\s\-]have|von vorteil|wünschenswert|ein plus|idealerweise|ideally|"
    r"(?:is|are) a plus|a bonus|un atout|un plus|souhaité|souhaitable|optional|preferred",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣]|\d{1,2}[.)])\s+")


class _Sections:
    def __init__(self, text: str) -> None:
        self.text = text
        self.starts: list[int] = [0]
        self.kinds: list[str] = ["other"]
        self.lines: list[tuple[int, str, str]] = []  # (offset, kind, line)
        offset = 0
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            kind = self._heading_kind(stripped)
            if kind is not None:
                self.starts.append(offset)
                self.kinds.append(kind)
            elif stripped:
                self.lines.append((offset, self.kinds[-1], stripped))
            offset += len(line)

    @staticmethod
    def _heading_kind(line: str) -> str | None:
        candidate = line.strip("#*_ \t").rstrip(":").strip()
        if not candidate or len(candidate) > 60 or _BULLET.match(line):
            return None
        if candidate.endswith((".", "!", "?")) and not line.endswith(":"):
            return None
        for kind, pattern in _HEADING_KINDS:
            if pattern.search(candidate):
                return kind
        return None

    def _kind_at(self, position: int) -> str:
        return self.kinds[bisect.bisect_right(self.starts, position) - 1]

    def is_required_at(self, position: int) -> bool:
        if self._kind_at(position) != "requirements":
            return False
        line_start = self.text.rfind("\n", 0, position) + 1
        line_end = self.text.find("\n", position)
        line = self.text[line_start : line_end if line_end != -1 else len(self.text)]
        return _OPTIONAL_LINE.search(line) is None

    def has_any(self, kinds: frozenset[str]) -> bool:
        return any(kind in kinds for kind in self.kinds)

    def text_outside(self, kinds: frozenset[str]) -> str:
        return "\n".join(line for _, kind, line in self.lines if kind not in kinds)

    def responsibility_lines(self) -> list[str]:
        return [
            _BULLET.sub("", line)
            for _, kind, line in self.lines
            if kind == "responsibilities" and len(line) >= 15
        ]


def text_without_requirements(text: str) -> str:
    """The posting without its requirements and nice-to-have sections.

    Names there are what the candidate should bring, so a letter must not
    adopt them as its own; the company, its products and the tasks stay.
    A posting without a recognizable requirements section gives no names at
    all: its requirements cannot be told apart, so the letter is checked
    against the profile alone.
    """
    sections = _Sections(text)
    kinds = frozenset({"requirements", "preferred"})
    return sections.text_outside(kinds) if sections.has_any(kinds) else ""
