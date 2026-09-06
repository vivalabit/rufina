import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.applications import (
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.documents import WorkspaceSourceDocumentRecord
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.privacy import AiPrivacySettingsRecord
from app.models.profile import ProfileFileRecord, ProfilePayload, ProfileRecord

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "seed_screenshot_workspace.py"
SPEC = importlib.util.spec_from_file_location("seed_screenshot_workspace", SCRIPT_PATH)
assert SPEC and SPEC.loader
seed_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seed_module
SPEC.loader.exec_module(seed_module)


def test_screenshot_fixture_is_valid_and_idempotent() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)

    with Session(engine) as db:
        first_summary = seed_module.seed_database(db, now=now)
        second_summary = seed_module.seed_database(db, now=now)

        profile_record = db.get(ProfileRecord, "default")
        assert profile_record is not None
        profile = ProfilePayload.model_validate(profile_record.data)
        assert profile.name == "Sofia"
        assert "resume_data_url" not in profile_record.data
        assert "documents" not in profile_record.data
        profile_file = db.query(ProfileFileRecord).filter_by(kind="primary_resume").one()
        assert profile_file.content.startswith(b"%PDF-1.4")

        assert db.query(StoredJobRecord).count() == 6
        assert db.query(JobMatchRecord).count() == 6
        assert db.query(StoredApplicationRecord).count() == 4
        assert db.query(WorkspaceSourceDocumentRecord).count() == 4
        assert all(
            "documents" not in record.data
            for record in db.query(StoredApplicationRecord).all()
        )
        assert db.query(StoredApplicationEventRecord).count() == 4
        assert db.query(AiPrivacySettingsRecord).count() == 1
        assert {record.score for record in db.query(JobMatchRecord).all()} == {
            64,
            71,
            77,
            83,
            88,
            94,
        }

    assert first_summary == second_summary
    assert first_summary == {
        "profile": "Sofia",
        "jobs": 6,
        "applications": 4,
        "events": 4,
    }


def test_screenshot_database_guard_rejects_primary_database() -> None:
    class DatabaseSession:
        def __init__(self, database_name: str) -> None:
            self.database_name = database_name

        def scalar(self, _statement: object) -> str:
            return self.database_name

    with pytest.raises(SystemExit, match="expected 'tasko_screenshots'"):
        seed_module.require_screenshot_database(DatabaseSession("tasko"))

    seed_module.require_screenshot_database(DatabaseSession("tasko_screenshots"))


def test_screenshot_reseed_preserves_non_demo_workspace_records() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    user_job_id = "manual-job-user-kept"
    user_application_id = "application-manual-job-user-kept"
    user_event_id = "user-event-kept"

    with Session(engine) as db:
        db.add(StoredJobRecord(id=user_job_id, data={"id": user_job_id}))
        db.add(
            StoredApplicationRecord(
                id=user_application_id,
                data={"id": user_application_id, "job": {"id": user_job_id}},
            )
        )
        db.add(
            StoredApplicationEventRecord(
                id=user_event_id,
                application_id=user_application_id,
                data={"id": user_event_id, "applicationId": user_application_id},
            )
        )
        db.add(ProfileRecord(id="user-profile-kept", data={"name": "User"}))
        db.commit()

        seed_module.seed_database(db, now=now)
        seed_module.seed_database(db, now=now)

        assert db.get(StoredJobRecord, ("local-owner", user_job_id)) is not None
        assert db.get(StoredApplicationRecord, user_application_id) is not None
        assert db.get(StoredApplicationEventRecord, user_event_id) is not None
        assert db.get(ProfileRecord, "user-profile-kept") is not None
        assert (
            db.query(StoredApplicationRecord)
            .filter(StoredApplicationRecord.id.like("application-manual-job-demo-%"))
            .count()
            == 4
        )
