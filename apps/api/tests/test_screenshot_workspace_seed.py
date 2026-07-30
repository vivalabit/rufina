import base64
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.settings import Settings
from app.models.applications import (
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.privacy import AiPrivacySettingsRecord
from app.models.profile import ProfilePayload, ProfileRecord

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
    settings = Settings(
        _env_file=None,
        app_env="local",
        database_url="sqlite://",
        ai_backend_mode="openclaw_codex",
    )
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)

    with Session(engine) as db:
        first_summary = seed_module.seed_database(db, settings, now=now)
        second_summary = seed_module.seed_database(db, settings, now=now)

        profile_record = db.get(ProfileRecord, "default")
        assert profile_record is not None
        profile = ProfilePayload.model_validate(profile_record.data)
        assert profile.name == "Maya Keller"
        assert profile.resume_data_url.startswith("data:application/pdf;base64,")
        encoded_pdf = profile.resume_data_url.partition(",")[2]
        assert base64.b64decode(encoded_pdf).startswith(b"%PDF-1.4")

        assert db.query(StoredJobRecord).count() == 6
        assert db.query(JobMatchRecord).count() == 6
        assert db.query(StoredApplicationRecord).count() == 4
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
        "profile": "Maya Keller",
        "jobs": 6,
        "applications": 4,
        "events": 4,
    }
