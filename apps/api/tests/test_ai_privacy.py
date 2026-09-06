from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import assistant as assistant_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.applications import CandidateConfirmationRecord
from app.models.assistant import AppliedAssistantActionRecord
from app.models.conversations import ConversationRecord
from app.models.documents import DocumentRecord, DocumentTemplateRecord
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.jobs import JobMatchRecord
from app.models.privacy import AiPrivacySettingsRecord
from app.models.profile import CandidateMatchSnapshotRecord, ProfilePayload, ProfileRecord
from app.services.ai_privacy import cleanup_expired_ai_data


def privacy_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_assistant_enabled=True,
    )
    return TestClient(app), testing_session_local


def test_ai_calls_run_directly_and_track_retention(monkeypatch) -> None:
    calls = 0

    async def run_assistant(**_kwargs):
        nonlocal calls
        calls += 1
        return "Generated response", "session-privacy"

    monkeypatch.setattr(assistant_api, "generate_assistant_with_facade", run_assistant)
    client, testing_session_local = privacy_client()
    headers = {"X-Rufina-Owner-Id": "privacy-owner"}
    with testing_session_local() as db:
        db.add(ProfileRecord(id="default", data=ProfilePayload().model_dump()))
        db.commit()

    try:
        initial = client.get("/privacy/ai-retention", headers=headers)
        allowed = client.post(
            "/assistant/chat",
            headers=headers,
            json={
                "threadId": "privacy-thread",
                "message": "Review my profile",
                "contextKind": "profile",
            },
        )
        allowed_match = client.post(
            "/jobs/ai-match",
            headers=headers,
            json={"jobs": []},
        )
        resume_import = client.post(
            "/profile/import-experience-from-resume",
            headers=headers,
            json={"profile_file_id": "missing-profile-file"},
        )
        retention = client.put(
            "/privacy/ai-retention",
            headers=headers,
            json={"retentionDays": 3},
        )
        after_retention_change = client.post(
            "/assistant/chat",
            headers=headers,
            json={
                "threadId": "privacy-thread",
                "message": "Review my profile again",
                "contextKind": "profile",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert initial.status_code == 200
    assert initial.json()["providerName"] == "OpenAI via OpenClaw/Codex"
    assert initial.json()["currentBackend"] == "openclaw_codex"
    assert allowed.status_code == 200
    assert allowed_match.status_code == 200
    assert resume_import.status_code != 403
    assert retention.status_code == 200
    assert retention.json()["retentionDays"] == 3
    assert after_retention_change.status_code == 200
    assert calls == 2

    with testing_session_local() as db:
        record = db.get(AiPrivacySettingsRecord, "privacy-owner")
        assert record is not None
        assert record.last_ai_activity_at is not None
        assert record.ai_data_expires_at is not None
        assert record.ai_data_expires_at - record.last_ai_activity_at == timedelta(days=3)


def test_retention_settings_survive_backend_changes() -> None:
    client, _ = privacy_client()
    headers = {"X-Rufina-Owner-Id": "backend-switch-owner"}

    try:
        configured = client.put(
            "/privacy/ai-retention",
            headers=headers,
            json={"retentionDays": 14},
        )
        app.dependency_overrides[get_settings] = lambda: Settings(
            ai_backend_mode="openai_api",
            openai_api_key="test-key",
        )
        after_switch = client.get("/privacy/ai-retention", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert configured.status_code == 200
    assert after_switch.status_code == 200
    assert after_switch.json()["providerName"] == "OpenAI Responses API"
    assert after_switch.json()["currentBackend"] == "openai_api"
    assert after_switch.json()["retentionDays"] == 14


def test_expired_ttl_deletes_only_the_owners_ai_data() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    now = datetime.now(UTC)

    with testing_session_local() as db:
        for owner_id, expired in (("expired-owner", True), ("active-owner", False)):
            db.add_all(
                [
                    AiPrivacySettingsRecord(
                        owner_id=owner_id,
                        retention_days=1,
                        last_ai_activity_at=now - timedelta(days=2),
                        ai_data_expires_at=(
                            now - timedelta(days=1)
                            if expired
                            else now + timedelta(days=1)
                        ),
                        updated_at=now,
                    ),
                    ConversationRecord(
                        id=f"conversation-{owner_id}",
                        owner_id=owner_id,
                        title="AI conversation",
                        context_kind="profile",
                        context_id="",
                        archived=False,
                        created_at=now,
                        updated_at=now,
                    ),
                    DocumentRecord(
                        id=f"document-{owner_id}",
                        owner_id=owner_id,
                        type="tailored_resume",
                        title="AI document",
                        current_version=1,
                        created_at=now,
                        updated_at=now,
                    ),
                    AppliedAssistantActionRecord(
                        id=f"action-{owner_id}",
                        owner_id=owner_id,
                        action_type="update_profile_field",
                        result={},
                        applied_at=now,
                    ),
                    CandidateMatchSnapshotRecord(
                        id=f"snapshot-{owner_id}",
                        owner_id=owner_id,
                        profile_input_hash="a" * 64,
                        profile_hash="b" * 64,
                        matcher_version="ai-match-v3",
                        source="openclaw_codex",
                        data={},
                        provider_error=None,
                        created_at=now,
                    ),
                    JobMatchRecord(
                        id=f"match-{owner_id}",
                        owner_id=owner_id,
                        job_id="job-privacy",
                        profile_hash="b" * 64,
                        matcher_version="ai-match-v3",
                        cache_key=f"cache-{owner_id}",
                        score=80,
                        source="openclaw_codex",
                        confidence="high",
                        breakdown={},
                        reasons=[],
                        gaps=[],
                        heuristic_score=75,
                        provider_error=None,
                        created_at=now,
                    ),
                    JobScreeningDecisionRecord(
                        id=f"screening-{owner_id}",
                        owner_id=owner_id,
                        vacancy_hash="c" * 64,
                        config_hash="d" * 64,
                        decision="reject",
                        reason_code="target_role_mismatch",
                        reason="Vacancy does not match the configured role",
                        matched_rule_ids=[],
                        model="openai/gpt-5-mini",
                        prompt_version="job-screening-prompt-v1",
                        title="Unrelated vacancy",
                        company="Example AG",
                        source_url="https://example.test/job",
                        created_at=now,
                    ),
                    DocumentTemplateRecord(
                        id=f"template-{owner_id}",
                        owner_id=owner_id,
                        type="tailored_resume",
                        name="Source CV",
                        file_name="resume.docx",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        content_sha256=owner_id.ljust(64, "0")[:64],
                        content=b"source",
                        extracted_text="Candidate-authored source",
                        created_at=now,
                        updated_at=now,
                    ),
                    CandidateConfirmationRecord(
                        application_id=f"application-{owner_id}",
                        question_id="leadership",
                        owner_id=owner_id,
                        requirement="Leadership",
                        response="yes",
                        example_text="Led a verified project",
                        blocking=True,
                        updated_at=now,
                    ),
                ]
            )
        db.commit()

        expired_owners, deleted_records = cleanup_expired_ai_data(db, now=now)

        assert expired_owners == 1
        assert deleted_records == 6
        assert db.get(ConversationRecord, "conversation-expired-owner") is None
        assert db.get(DocumentRecord, "document-expired-owner") is None
        assert db.get(JobMatchRecord, "match-expired-owner") is None
        assert db.get(
            JobScreeningDecisionRecord,
            "screening-expired-owner",
        ) is None
        assert db.get(DocumentTemplateRecord, "template-expired-owner") is not None
        assert db.get(
            CandidateConfirmationRecord,
            ("application-expired-owner", "leadership"),
        ) is not None
        assert db.get(ConversationRecord, "conversation-active-owner") is not None
        assert db.get(DocumentRecord, "document-active-owner") is not None
        assert db.get(JobMatchRecord, "match-active-owner") is not None
        assert db.get(
            JobScreeningDecisionRecord,
            "screening-active-owner",
        ) is not None
        expired_settings = db.get(AiPrivacySettingsRecord, "expired-owner")
        assert expired_settings is not None
        assert expired_settings.ai_data_expires_at is None


def test_delete_ai_data_preserves_other_owners() -> None:
    client, testing_session_local = privacy_client()
    now = datetime.now(UTC)
    with testing_session_local() as db:
        for owner_id in ("delete-owner", "keep-owner"):
            db.add_all(
                [
                    AiPrivacySettingsRecord(
                        owner_id=owner_id,
                        retention_days=30,
                        last_ai_activity_at=now,
                        ai_data_expires_at=now + timedelta(days=30),
                        updated_at=now,
                    ),
                    ConversationRecord(
                        id=f"conversation-{owner_id}",
                        owner_id=owner_id,
                        title="AI conversation",
                        context_kind="profile",
                        context_id="",
                        archived=False,
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
        db.commit()

    try:
        deleted = client.delete(
            "/privacy/ai-data",
            headers={"X-Rufina-Owner-Id": "delete-owner"},
        )
    finally:
        app.dependency_overrides.clear()

    assert deleted.status_code == 204
    with testing_session_local() as db:
        deleted_settings = db.get(AiPrivacySettingsRecord, "delete-owner")
        assert deleted_settings is not None
        assert deleted_settings.ai_data_expires_at is None
        assert db.get(ConversationRecord, "conversation-delete-owner") is None
        assert db.get(ConversationRecord, "conversation-keep-owner") is not None
