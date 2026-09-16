import hashlib
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.profile import ProfileVersionRecord
from app.models.resume import ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.profile_fact_sync import ProfileFactSyncError, confirm_profile_fact
from app.services.profile_migration import ensure_candidate_profile


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _data() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": "master-1",
        "language": "English",
        "basics": {"fullName": "Ada Lovelace"},
        "summary": None,
        "experiences": [],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [],
        "sectionOrder": [],
    }


def _hash(data: dict[str, object]) -> str:
    canonical = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _seed(sessions: sessionmaker[Session]) -> None:
    data = _data()
    master = ResumeMasterRecord(
        id="master-1", name="Ada Lovelace", language="English", current_version=1
    )
    master.versions.append(
        ResumeMasterVersionRecord(
            id="master-version-1",
            resume_master_id=master.id,
            version=1,
            schema_version="1.0",
            data=data,
            content_sha256=_hash(data),
        )
    )
    with sessions() as db:
        db.add(master)
        db.commit()
        ensure_candidate_profile(db)
        db.commit()


def test_confirmed_fact_creates_immutable_version_and_is_idempotent(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    with sessions() as db:
        first = confirm_profile_fact(
            db,
            master_resume_id="default",
            fact_text="Led a migration serving 100,000 monthly users.",
            expected_version=2,
            idempotency_key="run-1:answer-1",
            source_run_id="run-1",
        )
        retry = confirm_profile_fact(
            db,
            master_resume_id="default",
            fact_text="Led a migration serving 100,000 monthly users.",
            expected_version=2,
            idempotency_key="run-1:answer-1",
            source_run_id="run-1",
        )
        master = db.get(ResumeMasterRecord, "master-1")
        version = db.scalar(
            select(ProfileVersionRecord).where(
                ProfileVersionRecord.profile_id == "default",
                ProfileVersionRecord.revision == 3,
            )
        )

    assert first == retry
    assert first.to_version == 3
    assert master is not None and master.current_version == 1
    assert version is not None
    assert version.data["evidence"][0]["id"] == first.evidence_id
    assert version.data["additional_sections"][0]["items"][0]["text"].startswith("Led")


def test_stale_or_unconfirmed_fact_does_not_create_a_version(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    with sessions() as db:
        with pytest.raises(ProfileFactSyncError, match="changed"):
            confirm_profile_fact(
                db,
                master_resume_id="default",
                fact_text="Unconfirmed claim",
                expected_version=9,
                idempotency_key="stale-answer",
            )
        assert db.scalar(select(func.count()).select_from(ResumeMasterVersionRecord)) == 1


def test_confirmed_fact_targets_only_selected_experience(sessions):
    from app.services.candidate_profile import encode_entries, entries
    from app.services.profile_versions import update_profile_data

    with sessions() as db:
        profile = ensure_candidate_profile(db)
        data = dict(profile.data)
        data['experience'] = encode_entries([
            {'id': 'a', 'company': 'A', 'title': 'Engineer', 'description': 'Original A'},
            {'id': 'b', 'company': 'B', 'title': 'Engineer', 'description': 'Original B'},
        ])
        update_profile_data(db, profile, data=data, reason='test')
        db.commit()
        revision = profile.revision
        confirm_profile_fact(db, master_resume_id=profile.id, expected_version=revision,
                             fact_text='Confirmed detail', idempotency_key='target-a', experience_id='a')
        values = entries(profile.data['experience'], 'experience')
        assert values[0]['description'] == 'Original A\nConfirmed detail'
        assert values[1]['description'] == 'Original B'
        with pytest.raises(ProfileFactSyncError, match='changed'):
            confirm_profile_fact(db, master_resume_id=profile.id, expected_version=revision,
                                 fact_text='Stale detail', idempotency_key='stale', experience_id='b')
