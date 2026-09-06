import json
import subprocess
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings, get_settings
from app.main import app
from app.services.ai_backend import AIRequest, AIResult, AIUsage
from app.services.ai_privacy import record_ai_activity
from app.services.resume_import import (
    OpenClawResumeImportError,
    ResumeExperienceStructuredOutput,
    create_resume_import_ai_facade,
    extract_json_object,
    extract_openclaw_education_payload,
    extract_openclaw_experience_payload,
    parse_education_from_text,
    parse_experience_from_text,
    parse_experience_with_openclaw,
    parse_skills_from_text,
)


@pytest.fixture(autouse=True)
def bypass_ai_activity_tracking() -> Generator[None, None, None]:
    app.dependency_overrides[record_ai_activity] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(record_ai_activity, None)


def test_parse_experience_from_resume_text() -> None:
    entries = parse_experience_from_text(
        """
        PROFESSIONAL EXPERIENCE
        Senior Frontend Engineer | Rufina Labs | Jan 2024 - Present | Zurich, Switzerland
        Built job matching dashboards and profile workflows.
        Improved resume onboarding for candidates.

        Software Developer at Bright Apps
        Mar 2021 - Dec 2023
        Developed React and FastAPI features for internal tools.

        EDUCATION
        Computer Science
        """
    )

    assert len(entries) == 2
    assert entries[0].title == "Senior Frontend Engineer"
    assert entries[0].company == "Rufina Labs"
    assert entries[0].start_date == "2024-01"
    assert entries[0].is_current is True
    assert "profile workflows" in entries[0].description
    assert entries[1].title == "Software Developer"
    assert entries[1].company == "Bright Apps"
    assert entries[1].end_date == "2023-12"


def test_parse_education_from_resume_text() -> None:
    entries = parse_education_from_text(
        """
        PROFESSIONAL EXPERIENCE
        Python Developer | Alpine Systems | 2022 - Present
        Built API integrations.

        EDUCATION & CERTIFICATIONS
        ETH Zurich | Master of Science | Computer Science | Sep 2020 - Jun 2022 | Zurich, Switzerland
        Coursework: distributed systems and machine learning.

        AWS Certified Developer at Amazon Web Services
        2024 - 2024

        SKILLS
        Python, FastAPI
        """
    )

    assert len(entries) == 2
    assert entries[0].institution == "ETH Zurich"
    assert entries[0].credential == "Master of Science"
    assert entries[0].field_of_study == "Computer Science"
    assert entries[0].start_date == "2020-09"
    assert entries[0].end_date == "2022-06"
    assert "distributed systems" in entries[0].description
    assert entries[1].institution == "Amazon Web Services"
    assert entries[1].credential == "AWS Certified Developer"


def test_parse_skills_from_resume_text_deduplicates_case_insensitive() -> None:
    skills = parse_skills_from_text(
        """
        PROFESSIONAL EXPERIENCE
        Python Developer | Alpine Systems | 2022 - Present
        Built API integrations.

        Technical Skills
        Languages: Python, JavaScript, python
        Frameworks: FastAPI, React, Next.js
        Tools: Docker, GitHub Actions, CI/CD

        EDUCATION
        University of Zurich
        """
    )

    assert skills == [
        "Python",
        "JavaScript",
        "FastAPI",
        "React",
        "Next.js",
        "Docker",
        "GitHub Actions",
        "CI/CD",
    ]


def test_parse_experience_from_french_section_heading() -> None:
    entries = parse_experience_from_text(
        """
        Expérience professionnelle
        Software Engineer | Alpine Systems | 2022 - Present | Genève
        Built and operated reliable API integrations.

        Compétences techniques
        Python, FastAPI
        """
    )

    assert len(entries) == 1
    assert entries[0].title == "Software Engineer"
    assert entries[0].company == "Alpine Systems"


def test_parse_education_from_french_section_heading() -> None:
    entries = parse_education_from_text(
        """
        Formation académique
        Université de Genève | Master of Science | Informatique | 2020 - 2022

        IT‑Kenntnisse
        Python, FastAPI
        """
    )

    assert len(entries) == 1
    assert entries[0].institution == "Université de Genève"
    assert entries[0].credential == "Master of Science"


def test_parse_skills_from_unicode_hyphenated_german_section_heading() -> None:
    skills = parse_skills_from_text(
        """
        IT—Kenntnisse
        Sprachen: Python, JavaScript
        Frameworks: FastAPI, React

        Personalien
        Zürich, Schweiz
        """
    )

    assert skills == ["Python", "JavaScript", "FastAPI", "React"]


def test_import_experience_endpoint_reads_attached_resume_data() -> None:
    resume_text = """
    Work Experience
    Python Developer | Alpine Systems | 2022 - Present
    Automated reporting pipelines and built API integrations.
    Skills
    Python, FastAPI
    """
    client = TestClient(app)

    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    try:
        with (
            patch("app.api.profile.extract_resume_import_text", return_value=resume_text),
            patch(
                "app.api.profile.parse_resume_experience_with_selected_backend",
                return_value=parse_experience_from_text(resume_text),
            ),
        ):
            response = client.post(
                "/profile/import-experience-from-resume",
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["experience"][0]["title"] == "Python Developer"
    assert payload["experience"][0]["company"] == "Alpine Systems"
    assert payload["experience"][0]["is_current"] is True


def test_import_experience_reports_ai_failure_without_internal_details() -> None:
    resume_text = """
    Work Experience
    Python Developer | Alpine Systems | 2022 - Present
    Automated reporting pipelines and built API integrations.
    Skills
    Python, FastAPI
    """
    client = TestClient(app)

    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    try:
        with (
            patch("app.api.profile.extract_resume_import_text", return_value=resume_text),
            patch(
                "app.api.profile.parse_resume_experience_with_selected_backend",
                side_effect=OpenClawResumeImportError("internal analyzer details"),
            ),
        ):
            response = client.post(
                "/profile/import-experience-from-resume",
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "AI resume analysis is temporarily unavailable. Please try again."
    assert "internal analyzer details" not in response.text


@pytest.mark.parametrize(
    ("endpoint", "parser_path"),
    [
        (
            "/profile/import-education-from-resume",
            "app.api.profile.parse_resume_education_with_selected_backend",
        ),
        (
            "/profile/import-skills-from-resume",
            "app.api.profile.parse_resume_skills_with_selected_backend",
        ),
    ],
)
def test_all_resume_import_endpoints_hide_openclaw_failure_details(
    endpoint: str,
    parser_path: str,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    try:
        with (
            patch("app.api.profile.extract_resume_import_text", return_value="Resume text"),
            patch(
                parser_path,
                side_effect=OpenClawResumeImportError("provider credentials and command details"),
            ),
        ):
            response = TestClient(app).post(
                endpoint,
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "AI resume analysis is temporarily unavailable. Please try again."
    }
    assert "provider credentials" not in response.text


def test_import_experience_does_not_use_local_parser_when_ai_is_disabled() -> None:
    resume_text = """
    Work Experience
    Python Developer | Alpine Systems | 2022 - Present
    """
    client = TestClient(app)

    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=False)

    try:
        with patch("app.api.profile.extract_resume_import_text", return_value=resume_text):
            response = client.post(
                "/profile/import-experience-from-resume",
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "AI resume analysis is disabled."


def test_import_education_endpoint_reads_attached_resume_data() -> None:
    resume_text = """
    Work Experience
    Python Developer | Alpine Systems | 2022 - Present
    Automated reporting pipelines.

    Education
    University of Zurich | Bachelor of Science | Informatics | 2018 - 2021
    Certificates
    """
    client = TestClient(app)

    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    try:
        with (
            patch("app.api.profile.extract_resume_import_text", return_value=resume_text),
            patch(
                "app.api.profile.parse_resume_education_with_selected_backend",
                return_value=parse_education_from_text(resume_text),
            ),
        ):
            response = client.post(
                "/profile/import-education-from-resume",
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["education"][0]["institution"] == "University of Zurich"
    assert payload["education"][0]["credential"] == "Bachelor of Science"
    assert payload["education"][0]["field_of_study"] == "Informatics"


def test_import_skills_endpoint_reads_attached_resume_data() -> None:
    resume_text = """
    Work Experience
    Python Developer | Alpine Systems | 2022 - Present
    Automated reporting pipelines.

    Skills
    Python, FastAPI, Docker, PostgreSQL, Python

    Education
    University of Zurich
    """
    client = TestClient(app)

    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    try:
        with (
            patch("app.api.profile.extract_resume_import_text", return_value=resume_text),
            patch(
                "app.api.profile.parse_resume_skills_with_selected_backend",
                return_value=parse_skills_from_text(resume_text),
            ),
        ):
            response = client.post(
                "/profile/import-skills-from-resume",
                json={"profile_file_id": "profile-file-for-import"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["skills"] == ["Python", "FastAPI", "Docker", "PostgreSQL"]


def test_extract_json_object_reads_openclaw_json_output() -> None:
    payload = extract_json_object(
        """
        Here is the JSON:
        ```json
        {"experience":[]}
        ```
        """
    )

    assert payload == {"experience": []}


def test_extract_openclaw_experience_payload_reads_json_result_wrapper() -> None:
    payload = extract_openclaw_experience_payload(
        """
        [plugins] warning with config example {"plugins":{"allow":["codex"]}}
        {
          "status": "ok",
          "result": {
            "payloads": [
              {"text": "{\\"experience\\":[{\\"title\\":\\"Developer\\",\\"company\\":\\"Rufina\\",\\"employment_type\\":\\"Full-time\\",\\"location\\":\\"\\",\\"start_date\\":\\"2024-01\\",\\"end_date\\":\\"\\",\\"is_current\\":true,\\"description\\":\\"Built imports.\\"}]}"}
            ]
          }
        }
        """
    )

    assert payload["experience"][0]["title"] == "Developer"


def test_openclaw_resume_import_uses_a_fresh_isolated_session() -> None:
    output = json.dumps(
        {
            "payloads": [
                {
                    "text": json.dumps(
                        {
                            "experience": [
                                {
                                    "title": "Developer",
                                    "company": "Rufina",
                                    "employment_type": "Full-time",
                                    "location": "",
                                    "start_date": "2024-01",
                                    "end_date": "",
                                    "is_current": True,
                                    "description": "Built imports.",
                                }
                            ]
                        }
                    )
                }
            ]
        }
    )
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr="")

    with patch("app.services.resume_import.subprocess.run", return_value=completed) as run:
        for _ in range(2):
            parse_experience_with_openclaw(
                text="Developer at Rufina",
                command="openclaw",
                agent_id="rufina-assistant",
                thinking="high",
                timeout_seconds=120,
            )

    session_keys = []
    for call in run.call_args_list:
        command = call.args[0]
        session_keys.append(command[command.index("--session-key") + 1])

    assert all(key.startswith("agent:rufina-assistant:resume-import-") for key in session_keys)
    assert len(set(session_keys)) == 2


def test_resume_import_passes_strict_pydantic_output_model_to_backend() -> None:
    requests: list[AIRequest] = []

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return AIResult(
                text='{"experience":[]}',
                structured_data={"experience": []},
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="resp_resume_123",
            )

    assert parse_experience_with_openclaw(
        text="Developer at Rufina",
        command="openclaw",
        agent_id="rufina-assistant",
        thinking="low",
        timeout_seconds=30,
        model="gpt-5.6-terra",
        backend=FakeBackend(),
    ) == []

    assert requests[0].response_model is ResumeExperienceStructuredOutput


def test_resume_import_facade_uses_selected_openai_configuration() -> None:
    facade = create_resume_import_ai_facade(
        Settings(
            ai_backend_mode="openai_api",
            openai_api_key="test-key",
            openai_api_model="gpt-5.6-terra",
            openai_api_reasoning_effort="high",
            openai_api_timeout_seconds=75,
            openai_api_max_attempts=3,
            openai_api_retry_backoff_seconds=1.25,
        )
    )

    assert facade.backend.name == "openai_api"
    assert facade.model == "gpt-5.6-terra"
    assert facade.thinking == "high"
    assert facade.timeout_seconds == 75
    assert facade.max_attempts == 3
    assert facade.retry_backoff_seconds == 1.25


def test_extract_openclaw_education_payload_reads_json_result_wrapper() -> None:
    payload = extract_openclaw_education_payload(
        """
        [plugins] warning with config example {"plugins":{"allow":["codex"]}}
        {
          "status": "ok",
          "result": {
            "payloads": [
              {"text": "{\\"education\\":[{\\"institution\\":\\"Rufina University\\",\\"credential\\":\\"Certificate\\",\\"field_of_study\\":\\"AI\\",\\"location\\":\\"\\",\\"start_date\\":\\"2024-01\\",\\"end_date\\":\\"2024-12\\",\\"is_current\\":false,\\"description\\":\\"Built imports.\\"}]}"}
            ]
          }
        }
        """
    )

    assert payload["education"][0]["institution"] == "Rufina University"
