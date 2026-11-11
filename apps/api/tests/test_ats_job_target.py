import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.ai_backend import AIBackendError, AIRequest, AIResult, AIUsage
from app.services.ats.job_target import (
    EXTRACTOR_VERSION,
    InMemoryJobTargetCache,
    JobTargetExtractionError,
    JobTargetExtractor,
    JsonDirectoryJobTargetCache,
    VacancyInput,
    build_job_target_prompt,
    detect_posting_language,
    extract_job_target_without_model,
    job_target_cache_key,
    normalize_job_target,
    normalize_title,
    title_seniority,
)
from app.services.ats.models import JobSkill, JobTarget, JobTargetDraft

# Synthetic postings: no real employers or personal data.
EN_VACANCY = VacancyInput(
    title="Backend Engineer (f/m/x)",
    description="""About us
We are a fintech company in Zurich building payment APIs.

Your role
- Design and build REST APIs in Go and Python
- Run services on AWS with Terraform and Kubernetes
- Review code and mentor engineers

What you bring
- 4+ years of backend development experience
- Strong Python and Go skills; Python is our main language
- Experience with PostgreSQL and Kafka
- Familiarity with event sourcing is a plus
- Fluent English and native-level German
- Valid Swiss work permit

What we offer
- Hybrid work and a learning budget
""",
)

DE_VACANCY = VacancyInput(
    title="Senior Python-Entwickler (m/w/d) 80–100%",
    description="""Wir sind ein Softwarehaus in Zürich und suchen dich für unser Team.

Deine Aufgaben
- Du entwickelst Backend-Services mit Python und FastAPI
- Du betreibst unsere Services auf Kubernetes in der Azure Cloud
- Du arbeitest in einem agilen Scrum-Team

Dein Profil
- Mindestens 5 Jahre Erfahrung in der Softwareentwicklung
- Sehr gute Kenntnisse in Python und PostgreSQL
- Erfahrung mit Docker und CI/CD
- Kenntnisse in React sind von Vorteil
- Sehr gute Deutsch- und gute Englischkenntnisse

Wir bieten
- Moderne Arbeitsplätze und eine offene Kultur
""",
)

FR_SAMPLE = (
    "Nous recherchons pour notre équipe une personne avec de l'expérience dans "
    "les systèmes et vous êtes motivé par les défis. Votre profil est solide."
)


def _skill(surface: str, importance: str = "required", min_years: int | None = None) -> dict:
    return {"surface_form": surface, "importance": importance, "min_years": min_years}


def _knockout(kind: str, requirement: str, **values: Any) -> dict:
    return {
        "kind": kind,
        "requirement": requirement,
        "language": values.get("language"),
        "cefr_level": values.get("cefr_level"),
        "years": values.get("years"),
    }


EN_DRAFT: dict[str, Any] = {
    "title": "Backend Engineer",
    "seniority": "senior",
    "language": "en",
    "knockouts": [
        _knockout("experience", "4+ years of backend development experience"),
        _knockout("language", "Fluent English", language="English", cefr_level="C1"),
        _knockout("language", "native-level German", cefr_level="native"),
        _knockout("work_permit", "Valid Swiss work permit"),
        _knockout("work_permit", "valid swiss  work permit"),
        _knockout("location", "   "),
    ],
    "responsibilities": [
        "Design and build REST APIs in Go and Python",
        "design and build REST APIs in Go and Python",
        "Run services on AWS",
        " ",
    ],
    "skills": [
        _skill("Python", min_years=3),
        _skill("Go"),
        {**_skill("PostgreSQL", min_years=99), "importance": "Required"},
        _skill("Kafka"),
        _skill("Kubernetes", "preferred"),
        _skill("Python", "preferred", min_years=5),
        _skill("Rust"),
        _skill("Event Sourcing", "preferred"),
        _skill("payment APIs", "preferred"),
        _skill("AWS/Terraform"),
        _skill("deep understanding of distributed systems at very large scale"),
    ],
}


@dataclass
class FakeBackend:
    payload: Any = None
    error: AIBackendError | None = None
    name: str = "openai_api"
    calls: list[AIRequest] = field(default_factory=list)

    def generate(self, request: AIRequest) -> AIResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return AIResult(
            text="",
            structured_data=self.payload,
            model="test-model",
            backend=self.name,  # type: ignore[arg-type]
            usage=AIUsage(),
            latency_ms=1,
            session_id="",
        )

    async def agenerate(self, request: AIRequest) -> AIResult:
        return self.generate(request)


def _by_id(target: JobTarget) -> dict[str, JobSkill]:
    return {skill.key: skill for skill in target.skills}


def test_model_draft_is_normalized_against_text_and_dictionary() -> None:
    target = normalize_job_target(
        JobTargetDraft.model_validate(EN_DRAFT), EN_VACANCY, model="test-model"
    )
    skills = _by_id(target)

    assert [skill.key for skill in target.skills[:2]] == ["python", "go"]
    assert skills["python"].frequency == 3
    assert skills["python"].min_years == 5
    assert skills["python"].importance == "required"
    # "Go" is ambiguous in free text, but counts because the model named it.
    assert skills["go"].frequency == 2
    assert skills["go"].surface_form == "Go"
    assert skills["postgresql"].min_years is None
    assert skills["kubernetes"].importance == "preferred"
    # "AWS/Terraform" is split into two dictionary skills.
    assert skills["aws"].source == skills["terraform"].source == "model"
    # Exact vacancy wording wins over the model's casing.
    assert skills["event_driven"].surface_form == "event sourcing"
    # Outside the dictionary but present in the posting.
    assert skills["raw:payment apis"].canonical_id is None
    assert skills["raw:payment apis"].label == "payment APIs"
    # Not in the posting, or not a short skill name.
    assert "rust" not in skills
    assert not any("distributed" in key for key in skills)
    # Found by the dictionary only, in the responsibilities section.
    assert skills["rest_api"].source == "dictionary"
    assert skills["rest_api"].importance == "preferred"
    importance = [skill.importance for skill in target.skills]
    assert importance == sorted(importance, key=lambda value: value != "required")
    assert target.unmapped_skills == (skills["raw:payment apis"],)


def test_model_draft_title_language_knockouts_and_responsibilities() -> None:
    target = normalize_job_target(JobTargetDraft.model_validate(EN_DRAFT), EN_VACANCY)

    assert target.title == "Backend Engineer (f/m/x)"
    assert target.normalized_title == "backend engineer"
    assert target.seniority == "senior"
    assert target.language == "en"
    assert [(k.kind, k.language, k.cefr_level, k.years) for k in target.knockouts] == [
        ("experience", None, None, 4),
        ("language", "en", "C1", None),
        ("language", "de", "native", None),
        ("work_permit", None, None, None),
    ]
    assert target.responsibilities == (
        "Design and build REST APIs in Go and Python",
        "Run services on AWS",
    )
    assert target.extractor_version == EXTRACTOR_VERSION
    assert len(target.source_sha256) == 64


def test_dictionary_only_target_uses_sections_for_importance() -> None:
    target = extract_job_target_without_model(DE_VACANCY)
    skills = _by_id(target)

    assert target.normalized_title == "senior python-entwickler"
    assert target.seniority == "senior"
    assert target.language == "de"
    assert target.model == ""
    assert {key for key, skill in skills.items() if skill.importance == "required"} == {
        "python", "postgresql", "docker", "cicd",
    }
    # "von Vorteil" marks the line as optional even inside the profile section.
    assert skills["react"].importance == "preferred"
    assert skills["agile"].surface_form == "agilen"
    assert skills["python"].frequency == 3
    assert all(skill.source == "dictionary" for skill in target.skills)
    assert [(k.kind, k.years) for k in target.knockouts] == [("experience", 5)]
    assert target.responsibilities[0] == "Du entwickelst Backend-Services mit Python und FastAPI"
    assert len(target.responsibilities) == 3


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineer (w/m/d) 100%", "software engineer"),
        ("Data Analyst m/w/d, 80-100%", "data analyst"),
        ("Développeur Java (H/F)", "développeur java"),
        ("Lead Engineer (all genders)", "lead engineer"),
        ("Senior DevOps Engineer 80 bis 100 %", "senior devops engineer"),
    ],
)
def test_normalize_title(title: str, expected: str) -> None:
    assert normalize_title(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Praktikum Data Science 100%", "intern"),
        ("Lernende/r Informatiker/in EFZ", "intern"),
        ("Teamleiter Entwicklung (m/w/d)", "lead"),
        ("Sr. Backend Engineer", "senior"),
        ("Junior Developer", "junior"),
        ("Software Engineer", None),
    ],
)
def test_title_seniority(title: str, expected: str | None) -> None:
    assert title_seniority(title) == expected


def test_model_seniority_is_used_when_title_has_no_keyword() -> None:
    draft = JobTargetDraft.model_validate({**EN_DRAFT, "seniority": "MID"})

    assert normalize_job_target(draft, EN_VACANCY).seniority == "mid"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (EN_VACANCY.text, "en"),
        (DE_VACANCY.text, "de"),
        (FR_SAMPLE, "fr"),
        ("Python, Docker, AWS", None),
    ],
)
def test_detect_posting_language(text: str, expected: str | None) -> None:
    assert detect_posting_language(text) == expected


def test_extractor_calls_backend_once_and_caches() -> None:
    backend = FakeBackend(payload=EN_DRAFT)
    cache = InMemoryJobTargetCache()
    extractor = JobTargetExtractor(backend, cache=cache, model="gpt-test")

    first = extractor.extract(EN_VACANCY)
    second = extractor.extract(EN_VACANCY)

    assert first == second
    assert len(backend.calls) == 1
    request = backend.calls[0]
    assert request.structured is True
    assert request.response_model is JobTargetDraft
    assert request.model == "gpt-test"
    assert "Strong Python and Go skills" in request.prompt
    assert first.model == "test-model"
    assert len(cache.items) == 1


def test_prompt_contains_schema_but_not_the_dictionary() -> None:
    prompt = build_job_target_prompt(EN_VACANCY)

    assert '"surface_form"' in prompt
    assert "ambiguousAliases" not in prompt
    assert "Containerisierung" not in prompt


def test_json_directory_cache_round_trip(tmp_path: Path) -> None:
    cache = JsonDirectoryJobTargetCache(tmp_path / "targets")
    target = extract_job_target_without_model(DE_VACANCY)
    key = job_target_cache_key(DE_VACANCY, dictionary_version="v1", mode="dictionary")

    assert cache.get(key) is None
    cache.put(key, target)

    assert cache.get(key) == target
    assert '"surfaceForm"' in (tmp_path / "targets" / f"{key}.json").read_text()
    (tmp_path / "targets" / f"{key}.json").write_text("{broken")
    assert cache.get(key) is None
    assert cache.get("../escape") is None
    with pytest.raises(ValueError, match="sha256"):
        cache.put("../escape", target)


def test_cache_key_depends_on_content_dictionary_and_mode() -> None:
    base = job_target_cache_key(EN_VACANCY, dictionary_version="v1", mode="dictionary")

    assert base == job_target_cache_key(EN_VACANCY, dictionary_version="v1", mode="dictionary")
    assert base != job_target_cache_key(EN_VACANCY, dictionary_version="v2", mode="dictionary")
    assert base != job_target_cache_key(EN_VACANCY, dictionary_version="v1", mode="openai_api:x")
    assert base != job_target_cache_key(DE_VACANCY, dictionary_version="v1", mode="dictionary")


def test_backend_errors_raise_or_fall_back_without_caching() -> None:
    error = AIBackendError("timeout", code="timeout", retryable=True)
    backend = FakeBackend(error=error)
    cache = InMemoryJobTargetCache()

    with pytest.raises(JobTargetExtractionError, match="timeout"):
        JobTargetExtractor(backend, retry_backoff_seconds=0).extract(EN_VACANCY)
    assert len(backend.calls) == 2  # one retry for retryable errors

    fallback = JobTargetExtractor(
        backend, cache=cache, retry_backoff_seconds=0, fallback_to_dictionary=True
    ).extract(EN_VACANCY)

    assert fallback.model == ""
    assert all(skill.source == "dictionary" for skill in fallback.skills)
    assert cache.items == {}


def test_invalid_model_output_raises() -> None:
    backend = FakeBackend(payload={"title": "x", "skills": "Python"})

    with pytest.raises(JobTargetExtractionError, match="invalid structure"):
        JobTargetExtractor(backend).extract(EN_VACANCY)


def test_extractor_without_backend_is_dictionary_only() -> None:
    target = JobTargetExtractor(None).extract(DE_VACANCY)

    assert target == extract_job_target_without_model(DE_VACANCY)


def test_job_target_contract_is_strict() -> None:
    target = extract_job_target_without_model(DE_VACANCY)
    data = json.loads(target.model_dump_json(by_alias=True))

    assert JobTarget.model_validate_json(json.dumps(data)) == target
    assert data["skills"][0]["surfaceForm"] == "Python"
    with pytest.raises(ValidationError, match="extra"):
        JobTarget.model_validate_json(json.dumps({**data, "extra": 1}))
    with pytest.raises(ValidationError, match="unique"):
        JobTarget.model_validate_json(
            json.dumps({**data, "skills": [data["skills"][0], data["skills"][0]]})
        )
    with pytest.raises(ValidationError):
        JobTarget.model_validate_json(json.dumps({**data, "seniority": "guru"}))
    with pytest.raises(ValidationError):
        target.title = "changed"  # type: ignore[misc]


def test_draft_schema_marks_every_field_required() -> None:
    schema = JobTargetDraft.model_json_schema()
    objects = [schema, *schema.get("$defs", {}).values()]

    for definition in objects:
        properties = definition.get("properties", {})
        assert set(definition.get("required", [])) == set(properties), definition["title"]


def test_vacancy_input_from_job_data() -> None:
    listed = VacancyInput.from_job_data(
        {
            "title": "Data Engineer",
            "overview": "We build pipelines.",
            "requirements": ["Python", " Airflow "],
            "skills": ["dbt", 3],
        }
    )
    full = VacancyInput.from_job_data(
        {"title": "Data Engineer", "fullDescription": "Full text", "overview": "ignored"}
    )

    assert listed.description == "We build pipelines.\n- Python\n- Airflow\n- dbt"
    assert full.text == "Data Engineer\n\nFull text"
