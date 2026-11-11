import copy
import json

import pytest

from app.services.ats.skill_dictionary import (
    DEFAULT_SKILL_DICTIONARY_PATH,
    SkillDictionary,
    SkillDictionaryError,
    default_skill_dictionary,
)


def _ids(text: str, *, include_ambiguous: bool = False) -> list[str]:
    return [
        mention.skill_id
        for mention in default_skill_dictionary().scan(text, include_ambiguous=include_ambiguous)
    ]


def _minimal_data() -> dict:
    return {
        "schemaVersion": 1,
        "version": "test.1",
        "skills": [
            {
                "id": "python",
                "label": "Python",
                "category": "language",
                "aliases": {"en": ["Python"], "de": [], "fr": []},
                "caseSensitiveAliases": [],
                "ambiguousAliases": [],
            },
            {
                "id": "go",
                "label": "Go",
                "category": "language",
                "aliases": {"en": ["Golang"], "de": [], "fr": []},
                "caseSensitiveAliases": [],
                "ambiguousAliases": ["Go"],
            },
        ],
    }


def test_default_dictionary_loads_with_version_and_unique_ids() -> None:
    dictionary = default_skill_dictionary()
    raw = json.loads(DEFAULT_SKILL_DICTIONARY_PATH.read_text(encoding="utf-8"))

    assert dictionary.version == raw["version"]
    assert len(dictionary.entries) == len(raw["skills"]) >= 150
    assert all(entry.label and entry.category for entry in dictionary.entries.values())


def test_every_alias_in_the_data_file_resolves_to_its_own_skill() -> None:
    dictionary = default_skill_dictionary()
    for entry in dictionary.entries.values():
        for alias in entry.all_aliases:
            assert dictionary.lookup(alias) == entry.id, alias
        for alias in (entry.label, *entry.aliases, *entry.case_sensitive_aliases):
            if alias in entry.ambiguous_aliases:
                continue
            mentions = dictionary.scan(f"Experience with {alias} required.")
            assert [m.skill_id for m in mentions] == [entry.id], alias


def test_scan_prefers_the_longest_alias_and_respects_token_boundaries() -> None:
    text = "JavaScript, Java, C++, C#, ASP.NET Core and .NET; Spring-Boot and Spring Framework"

    assert _ids(text) == ["javascript", "java", "cpp", "csharp", "aspnet", "dotnet",
                          "spring_boot", "spring"]


def test_scan_handles_german_and_french_forms_and_compounds() -> None:
    text = (
        "Senior Python-Entwickler mit REST-Schnittstellen, Testautomatisierung und "
        "agilen Methoden. Maîtrise des tests unitaires et de l'apprentissage automatique."
    )

    assert _ids(text) == ["python", "rest_api", "test_automation", "agile", "unit_testing",
                          "machine_learning"]


def test_scan_returns_exact_surface_forms_and_offsets_in_normalized_text() -> None:
    dictionary = default_skill_dictionary()
    text = "Kubernetes (K8s) and Spring–Boot"

    mentions = dictionary.scan(text)

    assert [(m.skill_id, m.surface_form) for m in mentions] == [
        ("kubernetes", "Kubernetes"),
        ("kubernetes", "K8s"),
        ("spring_boot", "Spring-Boot"),
    ]
    assert text.replace("–", "-")[mentions[1].start : mentions[1].end] == "K8s"


@pytest.mark.parametrize(
    "text",
    [
        "You react quickly and excel at communication.",
        "The rest of the team will go live soon.",
        "Go live in Q3 with our R&D unit, plan C.",
        "Ideas that spark joy; nous utilisons un tableau de bord.",
    ],
)
def test_common_words_are_not_skills_in_free_text(text: str) -> None:
    assert _ids(text) == []


def test_ambiguous_aliases_only_match_inside_explicit_skill_phrases() -> None:
    assert _ids("C/C++, Go, R") == ["cpp"]
    assert _ids("C/C++, Go, R", include_ambiguous=True) == ["c", "cpp", "go", "r"]


def test_lookup_is_separator_and_case_insensitive_except_for_special_aliases() -> None:
    dictionary = default_skill_dictionary()

    assert dictionary.lookup("spring boot") == "spring_boot"
    assert dictionary.lookup("Python.") == "python"
    assert dictionary.lookup("Go") == "go"
    assert dictionary.lookup("go") is None
    assert dictionary.lookup("REST") == "rest_api"
    assert dictionary.lookup("rest") is None
    assert dictionary.lookup("Quantum Basket Weaving") is None


def test_custom_dictionary_from_data() -> None:
    dictionary = SkillDictionary.from_data(_minimal_data())

    assert dictionary.version == "test.1"
    assert [m.skill_id for m in dictionary.scan("Golang or Go and python")] == [
        "go",
        "python",
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(schemaVersion=2), "schema version"),
        (lambda d: d.update(version=" "), "version"),
        (lambda d: d["skills"].append(copy.deepcopy(d["skills"][0])), "Duplicate"),
        (lambda d: d["skills"][1]["aliases"]["en"].append("python"), "collides"),
        (lambda d: d["skills"][0]["aliases"].pop("fr"), "en/de/fr"),
        (lambda d: d["skills"][0]["aliases"]["de"].append("Python."), "Invalid alias"),
        (lambda d: d["skills"][0].update(id="Python"), "Invalid skill id"),
    ],
)
def test_invalid_dictionary_data_is_rejected(mutate, message: str) -> None:
    data = _minimal_data()
    mutate(data)

    with pytest.raises(SkillDictionaryError, match=message):
        SkillDictionary.from_data(data)
