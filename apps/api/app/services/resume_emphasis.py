"""Inline emphasis for resume statements: which parts of a bullet are set in bold.

A statement may carry explicit emphasis phrases. Without them, measurable
results and the technologies listed in the resume's own skills are emphasized.
Emphasis never changes the text; renderers that ignore it show the same words.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_UNITS = (
    "TB|GB|MB|KB|ms|sec|seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|"
    "Stunden|Tage|Wochen|Monate|Jahre"
)
_NUMBER = r"\d(?:[\d.,'’]*\d)?"
# A number with an optional range, a multiplier or percent sign and a unit:
# "30%", "1,000+", "7-8 TB", "under 24 hours" (only "24 hours" is emphasized).
_METRIC = re.compile(
    rf"(?<![\w.,])(?:[~≈<>]\s?|CHF\s?|EUR\s?|USD\s?|[$€£]\s?)?"
    rf"{_NUMBER}(?:\s?-\s?{_NUMBER})?"
    rf"(?:\s?(?:%|\+|(?:Mio\.?|bn|x|k|K|M)(?![\w])))?"
    rf"(?:\s(?:{_UNITS})\b)?"
)
_BARE_YEAR = re.compile(r"(?:19|20)\d{2}")
MAX_EMPHASIS_PHRASES = 8


@dataclass(frozen=True)
class TextSegment:
    text: str
    strong: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"text": self.text, "strong": self.strong}


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w+#]){re.escape(phrase)}(?![\w+#])")


def _spans_for_phrases(text: str, phrases: Iterable[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for phrase in sorted({item.strip() for item in phrases if item.strip()}, key=len, reverse=True):
        if len(phrase) < 2:
            continue
        spans.extend(match.span() for match in _phrase_pattern(phrase).finditer(text))
    return spans


def _metric_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in _METRIC.finditer(text):
        value = match.group().strip()
        if _BARE_YEAR.fullmatch(value) or not any(character.isdigit() for character in value):
            continue
        start = match.start() + (len(match.group()) - len(match.group().lstrip()))
        spans.append((start, start + len(value)))
    return spans


def _merge(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def emphasis_segments(
    text: str,
    *,
    explicit: Sequence[str] = (),
    technologies: Iterable[str] = (),
) -> list[TextSegment]:
    """Split a statement into plain and emphasized runs.

    Explicit phrases win. Otherwise metrics and known technologies are used.
    Phrases that do not occur verbatim are ignored.
    """
    spans = _spans_for_phrases(text, explicit)
    if not spans:
        spans = [*_metric_spans(text), *_spans_for_phrases(text, technologies)]
    segments: list[TextSegment] = []
    cursor = 0
    for start, end in _merge(spans):
        if start > cursor:
            segments.append(TextSegment(text[cursor:start]))
        segments.append(TextSegment(text[start:end], strong=True))
        cursor = end
    if cursor < len(text) or not segments:
        segments.append(TextSegment(text[cursor:]))
    return segments


def valid_emphasis(text: str, phrases: Iterable[str]) -> list[str]:
    """Keep only phrases that occur verbatim in the statement, in order of appearance."""
    found: list[tuple[int, str]] = []
    for phrase in dict.fromkeys(item.strip() for item in phrases if item and item.strip()):
        position = text.find(phrase)
        if position >= 0 and 2 <= len(phrase) <= 120:
            found.append((position, phrase))
    return [phrase for _, phrase in sorted(found)][:MAX_EMPHASIS_PHRASES]


__all__ = ["MAX_EMPHASIS_PHRASES", "TextSegment", "emphasis_segments", "valid_emphasis"]
