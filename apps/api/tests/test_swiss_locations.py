import json
from pathlib import Path

import pytest

from app.services.swiss_locations import resolve_swiss_cantons


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Stäfa", {"ZH"}),
        ("Staefa, Switzerland", {"ZH"}),
        ("STÄFA", {"ZH"}),
        ("stäfa zh", {"ZH"}),
        ("Stafa, Schweiz", {"ZH"}),
        ("CH-8712 Stäfa", {"ZH"}),
        ("8712", {"ZH"}),
        ("Winterthur", {"ZH"}),
        ("Dübendorf", {"ZH"}),
        ("Dubendorf", {"ZH"}),
        ("Duebendorf", {"ZH"}),
        ("Dietikon ZH, Zurich, Switzerland", {"ZH"}),
        ("Baden", {"AG"}),
        ("Liestal", {"BL"}),
        ("Basel BS", {"BS"}),
        ("4001 Basel", {"BS"}),
        ("Lausanne", {"VD"}),
        ("Lugano", {"TI"}),
        ("Chur", {"GR"}),
        ("Neuchâtel", {"NE"}),
        ("Sion", {"VS"}),
        ("Sitten", {"VS"}),
        ("Altdorf UR", {"UR"}),
        ("Stans", {"NW"}),
        ("Sarnen", {"OW"}),
        ("Schwyz", {"SZ"}),
        ("Zug", {"ZG"}),
        ("Glarus", {"GL"}),
        ("Frauenfeld", {"TG"}),
        ("Schaffhausen", {"SH"}),
        ("Solothurn", {"SO"}),
        ("Delémont", {"JU"}),
        ("Herisau AR", {"AR"}),
        ("Appenzell", {"AI"}),
        ("Luzern", {"LU"}),
        ("Murten", {"FR"}),
        ("Carouge GE", {"GE"}),
        ("St. Gallen SG", {"SG"}),
        ("Biel/Bienne, Switzerland", {"BE"}),
        ("Bienne", {"BE"}),
        ("Rapperswil-Jona", {"SG"}),
        ("Buchs SG", {"SG"}),
        ("Buchs, SG", {"SG"}),
        ("9470 Buchs", {"SG"}),
        ("CH-ZH", {"ZH"}),
        ("ch-zh", {"ZH"}),
        ("Kanton Zürich", {"ZH"}),
        ("Canton of Geneva", {"GE"}),
        ("canton de Vaud", {"VD"}),
        ("ZH", {"ZH"}),
        ("Stäfa, Switzerland (Hybrid)", {"ZH"}),
        ("Bern / Stäfa", {"BE", "ZH"}),
        ("Bern / Stäfa ZH", {"BE", "ZH"}),
        ("Bern - Stäfa ZH", {"BE", "ZH"}),
        ("Bern / Biel/Bienne", {"BE"}),
        ("Biel/Bienne BE", {"BE"}),
        ("ZH / BE", {"ZH", "BE"}),
        ("Bern; Lausanne; Stäfa", {"BE", "VD", "ZH"}),
        ("Zürich und Bern", {"BE", "ZH"}),
        ("Lausanne, Geneva", {"VD", "GE"}),
        ("Winterthur | Basel BS", {"ZH", "BS"}),
        ("Zürich und Basel BS", {"ZH", "BS"}),
        ("Bern / 8712 Stäfa", {"BE", "ZH"}),
        ("Zürich, ZH, Bern, BE", {"BE", "ZH"}),
    ],
)
def test_resolves_cantons_across_switzerland(location: str, expected: set[str]) -> None:
    assert resolve_swiss_cantons(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "",
        "Switzerland",
        "Schweiz",
        "CH",
        "Unknown",
        "Berlin, Germany",
        "Remote",
        "Bern (Remote)",
        "Home office / Bern",
        "Anywhere in Switzerland",
        "Buchs",
        "Rüti",
        "Rapperswil",
        "4052",  # Ambiguous names/postcodes.
        "Basel",
        "St. Gallen",
        "Herisau",
        "Dietikon",  # Cross-canton postal localities.
        "Bern / Unknown",
        "Unknown; Bern",
        "Basel or BL",
        "St. Gallen / AR",
        "Bern / Switzerland",
        "Bern and other locations",
        "Geneva, NY",
        "Freiburg, Germany",
        "Stäfa, Austria",
        "8712 Bern",
        "9999 Bern",  # Conflicting/unknown postcode evidence.
        "8712, Bern",
        "Stäfa, BE",
        "4051, Zürich",
        "Stäfa SG",
        "Zugermatt",
        "Zurichstrasse",
        "Stäfäli",  # No fuzzy substring matches.
    ],
)
def test_unknown_ambiguous_and_incomplete_locations_are_retained(location: str) -> None:
    assert resolve_swiss_cantons(location) == set()


def test_bundled_snapshot_covers_all_cantons_and_retains_attribution() -> None:
    path = Path(__file__).resolve().parents[1] / "app/data/swiss_localities.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert len(snapshot["rows"]) > 5000
    assert len({row[3] for row in snapshot["rows"]}) == 26
    assert snapshot["attribution"] == "Source: Federal Office of Topography swisstopo"
