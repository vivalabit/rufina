"""Conservative, offline Swiss canton resolution for vacancy location labels.

The bundled swisstopo snapshot covers the whole country. Unresolved, conflicting,
or ambiguous labels return no evidence so a canton filter cannot discard them.
Only the location field is inspected, never incidental place names in job text.
"""

import json
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

_CANTON_NAMES = {
    "AG": ("Aargau", "Argovie"),
    "AI": ("Appenzell Innerrhoden", "Appenzell Rhodes-Intérieures"),
    "AR": ("Appenzell Ausserrhoden", "Appenzell Rhodes-Extérieures"),
    "BE": ("Bern", "Berne", "Berna"),
    "BL": ("Basel-Landschaft", "Basel Land", "Baselland", "Bâle-Campagne"),
    "BS": ("Basel-Stadt", "Basel", "Basle", "Bâle", "Bâle-Ville"),
    "FR": ("Fribourg", "Freiburg"),
    "GE": ("Genève", "Geneva", "Genf", "Ginevra"),
    "GL": ("Glarus", "Glaris", "Glarona"),
    "GR": ("Graubünden", "Grisons", "Grigioni"),
    "JU": ("Jura",),
    "LU": ("Luzern", "Lucerne", "Lucerna"),
    "NE": ("Neuchâtel", "Neuenburg"),
    "NW": ("Nidwalden", "Nidwald"),
    "OW": ("Obwalden", "Obwald"),
    "SG": ("St. Gallen", "Sankt Gallen", "Saint-Gall", "San Gallo"),
    "SH": ("Schaffhausen", "Schaffhouse", "Sciaffusa"),
    "SO": ("Solothurn", "Soleure", "Soletta"),
    "SZ": ("Schwyz", "Schwytz", "Svitto"),
    "TG": ("Thurgau", "Thurgovie", "Turgovia"),
    "TI": ("Ticino", "Tessin"),
    "UR": ("Uri",),
    "VD": ("Vaud", "Waadt"),
    "VS": ("Valais", "Wallis", "Vallese"),
    "ZG": ("Zug", "Zoug", "Zugo"),
    "ZH": ("Zürich", "Zurich", "Zurigo"),
}
_COUNTRIES = {"switzerland", "schweiz", "suisse", "svizzera", "svizra", "ch", "che"}
_MODES = r"hybrid|hybride|hybrides arbeiten|on[- ]site|onsite|vor ort|vor-ort"
_MODE_SUFFIX = re.compile(rf"\s*(?:\((?:{_MODES})\)|[-–—,]\s*(?:{_MODES}))\s*$", re.IGNORECASE)
_REMOTE = re.compile(
    r"\b(remote|home\s*office|anywhere|schweizweit|switzerland-wide)\b", re.IGNORECASE
)
_SEPARATORS = re.compile(r"\s*(?:[/;|&\n]|\s+(?:and|or|und|oder|et|ou|[-–—])\s+)\s*", re.IGNORECASE)
_CANTON_PREFIX = re.compile(
    r"^(?:canton(?:\s+(?:of|de|du))?|kanton|cantone(?:\s+di)?)\s+", re.IGNORECASE
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\b(?:saint|sankt)\b", "st", value)
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def _name_keys(name: str) -> set[str]:
    # Generate aliases from the authoritative spelling, without changing arbitrary
    # input words (e.g. replacing every 'ue' in a French place would be unsafe).
    transliterated = name.casefold().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"}))
    names = {name, transliterated}
    suffix_pattern = r"\s+\(?(?:" + "|".join(_CANTON_NAMES) + r")\)?$"
    names.update(re.sub(suffix_pattern, "", name, flags=re.IGNORECASE) for name in tuple(names))
    return {_normalize(item) for item in names if item}


@lru_cache(maxsize=1)
def _locality_rows() -> list[list[str]]:
    path = Path(__file__).resolve().parents[1] / "data" / "swiss_localities.json"
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def is_swiss_postal_locality(locality: str, postcode: str) -> bool:
    """Verify the exact postal code/name pair against the swisstopo directory."""
    key = _normalize(locality)
    return bool(key and re.fullmatch(r"\d{4}", postcode)) and any(
        row[1] == postcode and key in (_name_keys(row[0]) | _name_keys(row[2]))
        for row in _locality_rows()
    )


@lru_cache(maxsize=1)
def _bilingual_names() -> re.Pattern[str]:
    names = {name for row in _locality_rows() for name in (row[0], row[2]) if "/" in name}
    return re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(name) for name in sorted(names)) + r")(?!\w)",
        re.IGNORECASE,
    )


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    names: dict[str, set[str]] = defaultdict(set)
    postcodes: dict[str, set[str]] = defaultdict(set)
    canton_names: dict[str, set[str]] = defaultdict(set)
    for locality, postcode, municipality, canton in _locality_rows():
        if canton not in _CANTON_NAMES:
            continue
        for name in (locality, municipality):
            for key in _name_keys(name):
                names[key].add(canton)
        postcodes[postcode].add(canton)
    for canton, aliases in _CANTON_NAMES.items():
        for alias in aliases:
            for key in _name_keys(alias):
                canton_names[key].add(canton)
    # Bilingual official names also occur with just one language on job boards.
    for alias, official in (
        ("Biel", "Biel/Bienne"),
        ("Bienne", "Biel/Bienne"),
        ("Coire", "Chur"),
        ("Coira", "Chur"),
        ("Sion", "Sion"),
        ("Sitten", "Sion"),
        ("Sierre", "Sierre"),
        ("Siders", "Sierre"),
    ):
        names[_normalize(alias)].update(names[_normalize(official)])
    return dict(names), dict(postcodes), dict(canton_names)


def _part_candidates(value: str) -> set[str]:
    names, postcodes, canton_names = _indexes()
    explicit_canton_name = bool(_CANTON_PREFIX.match(value.strip()))
    value = _CANTON_PREFIX.sub("", value.strip())
    # Codes are trusted only as complete labels, ISO CH-XX codes, or suffixes.
    code_match = re.fullmatch(r"(?:CH[- ])?([A-Za-z]{2})", value, flags=re.IGNORECASE)
    if code_match and code_match[1].upper() in _CANTON_NAMES:
        return {code_match[1].upper()}
    suffix = re.search(r"(?:\s+|\s*\()([A-Z]{2})\)?$", value, flags=re.IGNORECASE)
    explicit = {suffix[1].upper()} if suffix and suffix[1].upper() in _CANTON_NAMES else set()
    if explicit:
        value = value[: suffix.start()].strip()
    value = re.sub(r"^CH[- ](?=\d{4}\b)", "", value, flags=re.IGNORECASE)
    postal_matches = re.findall(r"(?<!\w)\d{4}(?!\w)", value)
    postal = set()
    if len(postal_matches) == 1:
        postal = postcodes.get(postal_matches[0], set())
        if not postal:
            return set()
        value = re.sub(r"(?<!\w)\d{4}(?!\w)", "", value).strip()
    elif postal_matches:
        return set()
    key = _normalize(value)
    # A postal locality can cross a cantonal boundary (Basel, for example).
    # A bare city name must retain that ambiguity; an explicit canton name can
    # still select the canton itself, e.g. "Kanton Basel-Stadt".
    named = (
        canton_names.get(key, set())
        if explicit_canton_name
        else names.get(key, set()) | canton_names.get(key, set())
    )
    evidence = [item for item in (explicit, postal, named) if item]
    if not evidence:
        return set()
    candidates = set.intersection(*evidence)
    return candidates


def resolve_swiss_cantons(location: str) -> set[str]:
    """Return confidently resolved cantons, or empty evidence to retain the job.

    Multiple known locations are combined. If any location is unknown or
    ambiguous, the whole label remains unresolved. Remote/broad locations are
    kept as well: an office outside the selection need not be the workplace.
    """
    if not location or _REMOTE.search(location):
        return set()
    label = _MODE_SUFFIX.sub("", location.strip())
    # Split before looking for postcode/canton suffixes: the last location's
    # qualifiers must never swallow earlier places in a multi-location label.
    # Keep official bilingual names (Biel/Bienne) intact.
    label = _bilingual_names().sub(lambda match: match[0].replace("/", " "), label)
    result: set[str] = set()
    for group in _SEPARATORS.split(label):
        evidence: list[tuple[set[str], bool]] = []
        for part in group.split(","):
            part = part.strip()
            if _normalize(part) in _COUNTRIES:
                continue
            candidates = _part_candidates(part)
            # Only address-like comma separators attach qualifiers. A slash,
            # "or", etc. starts an independent location and must not narrow the
            # previous place (e.g. "Basel / BL" includes an ambiguous Basel).
            qualifier = bool(re.fullmatch(r"(?:CH[- ])?(?:[A-Za-z]{2}|\d{4})", part, re.IGNORECASE))
            if evidence and qualifier != evidence[-1][1]:
                previous, _ = evidence.pop()
                evidence.append((previous & candidates, False))
            else:
                evidence.append((candidates, qualifier))
        if not evidence:
            return set()
        for candidates, _ in evidence:
            if len(candidates) != 1:
                return set()
            result.update(candidates)
    return result
