"""Model wording for planned statements, and the checks that keep it factual.

The model receives selected profile statements and returns one rewritten bullet
per statement, keyed by its ID. Code then compares every rewritten bullet with
its source: new numbers, technologies, product names or employers reject the
bullet. A rejected bullet is retried once and otherwise keeps the profile's own
wording, so one bad sentence never fails a document.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from app.models.resume import MasterResume
from app.services.ats.models import JobTarget
from app.services.ats.planner import (
    DocumentLanguage,
    PlannedStatement,
    TailoringPlan,
    mentions_term,
)
from app.services.ats.profile_index import ProfileIndex
from app.services.ats.skill_dictionary import SkillDictionary, normalize_text
from app.services.resume_emphasis import valid_emphasis

LANGUAGE_NAMES: dict[DocumentLanguage, str] = {"en": "English", "de": "German", "fr": "French"}
MIN_STATEMENT_CHARS = 240
STATEMENT_GROWTH = 1.4
MAX_SUMMARY_CHARS = 360
MAX_RESPONSIBILITIES_IN_PROMPT = 8
MAX_PREFERENCES_CHARS = 2_000
_NUMBER = re.compile(r"\d+(?:[.,'’]\d+)*")
_GROUPED_THOUSANDS = re.compile(r"\d{1,3}(?:[.,'’]\d{3})+")
# Tokens that look like a product, protocol or acronym: two or more capitals,
# camel case, or letters mixed with digits or symbols ("JWT", "VirusTotal", "S3").
# Hyphens and slashes separate tokens, so "ML-powered" is checked as "ML".
_NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[+#.][A-Za-z0-9+#]+)*[+#]*")
# Abbreviations a translation may introduce without adding a fact.
_NEUTRAL_ACRONYMS = frozenset({
    "KI", "IT", "EDV", "API", "APIS", "UI", "UX", "QA", "KPI", "KPIS", "CI", "CD", "PDF",
    "USA", "EU", "CH", "ID", "IDS",
})
# Broad terms a summary or letter may use without naming a specific fact.
_FREE_TEXT_ACRONYMS = _NEUTRAL_ACRONYMS | {"AI", "ML", "CV", "HR", "SAAS", "B2B", "B2C"}


class WordingModel(BaseModel):
    """Lenient base for model output; all fields required, as strict schemas need."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class StatementWording(WordingModel):
    id: str
    text: str
    emphasis: list[str]


class WordingDraft(WordingModel):
    summary: str
    statements: list[StatementWording]


@dataclass(frozen=True)
class GuardResult:
    issues: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class WordedStatement:
    statement_id: str
    text: str
    emphasis: tuple[str, ...]
    origin: str  # "model" or "master"
    issues: tuple[str, ...] = ()


def number_tokens(text: str) -> set[str]:
    """Numbers in a comparable form: "5,000", "5'000" and "5000" are the same."""
    tokens: set[str] = set()
    for match in _NUMBER.finditer(text):
        token = match.group()
        if _GROUPED_THOUSANDS.fullmatch(token):
            token = re.sub(r"[.,'’]", "", token)
        else:
            token = token.replace("’", "").replace("'", "").replace(",", ".")
        tokens.add(token.lstrip("0") or "0")
    return tokens


def _is_name_token(token: str) -> bool:
    capitals = sum(1 for character in token if character.isupper())
    has_digit = any(character.isdigit() for character in token)
    has_symbol = any(character in "+#." for character in token)
    return capitals >= 2 or (has_digit and any(c.isalpha() for c in token)) or has_symbol


def name_tokens(text: str) -> set[str]:
    return {
        match.group().strip(".").casefold()
        for match in _NAME_TOKEN.finditer(normalize_text(text))
        if _is_name_token(match.group().strip("."))
    }


def _is_known_name(token: str, known: set[str]) -> bool:
    """A known name, its plural, or a part of a longer known name."""
    return (
        token in known
        or token.removesuffix("s") in known
        or any(token in name for name in known)
    )


def check_statement(
    text: str,
    *,
    source: str,
    terms: Sequence[str] = (),
    other_employers: Iterable[str] = (),
    dictionary: SkillDictionary,
    translated: bool = False,
) -> GuardResult:
    """Reject wording that states anything its source statement does not contain."""
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        return GuardResult(("empty text",))
    if "\n" in cleaned:
        issues.append("contains a line break")
    limit = max(MIN_STATEMENT_CHARS, int(len(source) * STATEMENT_GROWTH))
    if len(cleaned) > limit:
        issues.append(f"longer than {limit} characters")

    allowed_context = "\n".join([source, *terms])
    new_numbers = number_tokens(cleaned) - number_tokens(allowed_context)
    if new_numbers:
        issues.append(f"new numbers: {', '.join(sorted(new_numbers))}")

    allowed_skills = {mention.skill_id for mention in dictionary.scan(allowed_context)}
    for term in terms:
        if resolved := dictionary.lookup(term):
            allowed_skills.add(resolved)
    new_skills = sorted(
        {
            mention.surface_form
            for mention in dictionary.scan(cleaned)
            if mention.skill_id not in allowed_skills
        }
    )
    if new_skills:
        issues.append(f"new technologies: {', '.join(new_skills)}")

    known_names = name_tokens(allowed_context)
    new_names = sorted(
        token
        for token in name_tokens(cleaned) - known_names
        if not (translated and token.upper() in _NEUTRAL_ACRONYMS)
        and not _is_known_name(token, known_names)
        and token not in {skill.casefold() for skill in new_skills}
    )
    if new_names:
        issues.append(f"new names: {', '.join(new_names)}")

    for employer in other_employers:
        if (
            len(employer) >= 4
            and mentions_term(cleaned, employer)
            and not mentions_term(source, employer)
        ):
            issues.append(f"names another employer: {employer}")
    return GuardResult(tuple(issues))


def check_free_text(
    text: str,
    *,
    allowed_context: str,
    allowed_skill_ids: Iterable[str],
    dictionary: SkillDictionary,
    max_chars: int,
    names_context: str = "",
) -> GuardResult:
    """Guard for a summary or letter paragraph built from several profile facts.

    `names_context` may add names, such as the vacancy's company and products,
    without allowing their numbers or technologies.
    """
    issues: list[str] = []
    cleaned = text.strip()
    if not cleaned:
        return GuardResult(("empty text",))
    if len(cleaned) > max_chars:
        issues.append(f"longer than {max_chars} characters")
    new_numbers = number_tokens(cleaned) - number_tokens(allowed_context)
    if new_numbers:
        issues.append(f"new numbers: {', '.join(sorted(new_numbers))}")
    allowed = set(allowed_skill_ids) | {
        mention.skill_id for mention in dictionary.scan(allowed_context)
    }
    new_skills = sorted(
        {
            mention.surface_form
            for mention in dictionary.scan(cleaned)
            if mention.skill_id not in allowed
        }
    )
    if new_skills:
        issues.append(f"new technologies: {', '.join(new_skills)}")
    known_names = name_tokens(f"{allowed_context}\n{names_context}")
    new_names = sorted(
        token
        for token in name_tokens(cleaned) - known_names
        if token.upper() not in _FREE_TEXT_ACRONYMS
        and not _is_known_name(token, known_names)
        and token not in {skill.casefold() for skill in new_skills}
    )
    if new_names:
        issues.append(f"new names: {', '.join(new_names)}")
    return GuardResult(tuple(issues))


def statement_char_limit(source: str) -> int:
    return max(MIN_STATEMENT_CHARS, int(len(source) * STATEMENT_GROWTH)) - 20


def years_of_experience(index: ProfileIndex) -> int:
    return index.total_months // 12


def swiss_spelling(text: str, *, language: DocumentLanguage, vacancy_text: str) -> str:
    """Follow the posting's convention: Swiss German texts write "ss" for "ß"."""
    if language == "de" and "ß" not in vacancy_text:
        return text.replace("ß", "ss")
    return text


def _vacancy_block(target: JobTarget, plan: TailoringPlan) -> dict[str, object]:
    return {
        "title": target.title,
        "requiredSkills": [skill.surface_form for skill in target.required_skills],
        "preferredSkills": [skill.surface_form for skill in target.preferred_skills],
        "mainTasks": list(target.responsibilities[:MAX_RESPONSIBILITIES_IN_PROMPT]),
        "skillsTheCandidateHas": [
            match.label for match in plan.matches if match.support != "gap"
        ],
    }


def build_wording_prompt(
    *,
    master: MasterResume,
    index: ProfileIndex,
    target: JobTarget,
    plan: TailoringPlan,
    statements: Sequence[PlannedStatement],
    user_preferences: str = "",
    retry_issues: dict[str, Sequence[str]] | None = None,
    include_summary: bool = True,
) -> str:
    roles = {experience.id: experience for experience in master.experiences}
    items = []
    for planned in statements:
        role = roles[planned.statement.experience_id]
        item: dict[str, object] = {
            "id": planned.statement.id,
            "role": f"{role.title}, {role.company}",
            "statement": planned.statement.text,
            "maxChars": statement_char_limit(planned.statement.text),
        }
        if planned.terms:
            item["useTerms"] = list(planned.terms)
        if retry_issues and planned.statement.id in retry_issues:
            item["previousAttemptRejectedBecause"] = list(retry_issues[planned.statement.id])
        items.append(item)
    years = years_of_experience(index)
    summary_facts = {
        "currentHeadline": plan.headline,
        "yearsOfExperience": years if years >= 1 else None,
        "profileSummary": master.summary.text if master.summary else "",
    }
    language = LANGUAGE_NAMES[plan.language]
    summary_rule = (
        "8. summary: at most two sentences and "
        f"{MAX_SUMMARY_CHARS - 40} characters, without \"I\", that position the candidate for "
        "this vacancy. Use only summaryFacts, skillsTheCandidateHas and the statements. "
        "State years of experience only if yearsOfExperience is given. No new numbers."
        if include_summary
        else '8. summary: return an empty string "".'
    )
    preferences = user_preferences.strip()[:MAX_PREFERENCES_CHARS]
    lines = [
        (
            "You tailor resume statements to one vacancy. You rephrase only: every fact in "
            "your text must come from the statement you are rewriting."
        ),
        "",
        f"Write in {language}."
        + (" Use Swiss Standard German spelling (ss instead of ß)." if plan.language == "de" else ""),
        "",
        "Rules:",
        (
            "1. Rewrite each statement as one resume bullet: lead with the result when the "
            "statement has one, use a strong action verb, no first person, end with a period."
        ),
        (
            "2. Keep every number, metric, product name and technology name exactly as "
            "written. Never add a number, technology, tool, employer, team size, scope or "
            "outcome that the statement does not contain."
        ),
        (
            "3. When useTerms is given, the statement already names that skill with another "
            "spelling: use the given spelling verbatim instead."
        ),
        (
            "4. Where the vacancy uses another word for the same task, prefer the vacancy's "
            "word. Do not claim tasks that the statement does not describe."
        ),
        (
            "5. Stay within maxChars. Never merge or split statements. Return every id "
            "exactly once and nothing else."
        ),
        (
            "6. If a statement is already strong and relevant, change little. Technology "
            "names stay in their original spelling in every language."
        ),
        (
            "7. emphasis: up to three short phrases copied verbatim from your rewritten text "
            "that a recruiter should notice first, such as a metric or a key technology."
        ),
        summary_rule,
    ]
    if preferences:
        lines += ["", "The candidate's style wishes (they never add facts): " + preferences]
    lines += [
        "",
        (
            'Return only JSON of this shape: {"summary": "...", "statements": '
            '[{"id": "...", "text": "...", "emphasis": ["..."]}]}'
        ),
        "",
        "Vacancy:",
        json.dumps(_vacancy_block(target, plan), ensure_ascii=False),
        "",
        "summaryFacts:",
        json.dumps(summary_facts, ensure_ascii=False),
        "",
        "Statements:",
        json.dumps(items, ensure_ascii=False, indent=1),
    ]
    return "\n".join(lines)


def parse_wording_draft(data: object) -> WordingDraft:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    try:
        return WordingDraft.model_validate(data)
    except ValidationError as exc:
        raise ValueError("Wording response has an invalid structure") from exc


def evaluate_wording(
    draft: WordingDraft,
    *,
    master: MasterResume,
    plan: TailoringPlan,
    statements: Sequence[PlannedStatement],
    dictionary: SkillDictionary,
    vacancy_text: str,
) -> tuple[dict[str, WordedStatement], dict[str, tuple[str, ...]]]:
    """Accept the bullets that pass the guard; return the rest with their issues."""
    translated = plan.language != language_code(master.language)
    employers = {
        experience.id: experience.company for experience in master.experiences
    }
    by_id = {item.id: item for item in draft.statements}
    accepted: dict[str, WordedStatement] = {}
    rejected: dict[str, tuple[str, ...]] = {}
    for planned in statements:
        statement = planned.statement
        proposal = by_id.get(statement.id)
        if proposal is None:
            rejected[statement.id] = ("missing from the response",)
            continue
        text = swiss_spelling(
            " ".join(proposal.text.split()), language=plan.language, vacancy_text=vacancy_text
        )
        result = check_statement(
            text,
            source=statement.text,
            terms=planned.terms,
            other_employers=[
                company
                for experience_id, company in employers.items()
                if experience_id != statement.experience_id
            ],
            dictionary=dictionary,
            translated=translated,
        )
        if result.ok:
            accepted[statement.id] = WordedStatement(
                statement_id=statement.id,
                text=text,
                emphasis=tuple(valid_emphasis(text, proposal.emphasis)[:3]),
                origin="model",
            )
        else:
            rejected[statement.id] = result.issues
    return accepted, rejected


def language_code(language: str) -> DocumentLanguage:
    text = language.strip().casefold()
    if text.startswith(("de", "german", "deutsch")):
        return "de"
    if text.startswith(("fr", "french", "français", "francais")):
        return "fr"
    return "en"


def master_wording(planned: PlannedStatement, issues: Sequence[str] = ()) -> WordedStatement:
    return WordedStatement(
        statement_id=planned.statement.id,
        text=planned.statement.text,
        emphasis=(),
        origin="master",
        issues=tuple(issues),
    )


def evaluate_summary(
    summary: str,
    *,
    master: MasterResume,
    index: ProfileIndex,
    plan: TailoringPlan,
    dictionary: SkillDictionary,
    vacancy_text: str,
) -> tuple[str, tuple[str, ...]]:
    """Return the accepted summary, or an empty string with the reasons it was rejected."""
    text = swiss_spelling(
        " ".join(summary.split()), language=plan.language, vacancy_text=vacancy_text
    )
    if not text:
        return "", ()
    years = years_of_experience(index)
    context = "\n".join(
        [
            master.summary.text if master.summary else "",
            plan.headline,
            str(years) if years >= 1 else "",
            *(skill.name for skill in master.skills),
            *(planned.statement.text for planned in plan.statements),
            *(experience.title for experience in master.experiences),
        ]
    )
    result = check_free_text(
        text,
        allowed_context=context,
        allowed_skill_ids=index.skill_ids,
        dictionary=dictionary,
        max_chars=MAX_SUMMARY_CHARS,
    )
    return (text, ()) if result.ok else ("", result.issues)


__all__ = [
    "LANGUAGE_NAMES",
    "MAX_PREFERENCES_CHARS",
    "GuardResult",
    "StatementWording",
    "WordedStatement",
    "WordingDraft",
    "WordingModel",
    "build_wording_prompt",
    "check_free_text",
    "check_statement",
    "evaluate_summary",
    "evaluate_wording",
    "language_code",
    "master_wording",
    "name_tokens",
    "number_tokens",
    "parse_wording_draft",
    "statement_char_limit",
    "swiss_spelling",
    "years_of_experience",
]
