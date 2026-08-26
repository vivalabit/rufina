from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.job_filter import JobFilterSettingsRecord


def job_filter_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), testing_session_local


def test_get_missing_job_filter_settings_returns_default_without_insert() -> None:
    client, sessions = job_filter_client()

    try:
        response = client.get(
            "/job-search/filter-settings",
            headers={"X-Rufina-Owner-Id": "owner-a"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "schemaVersion": 1,
        "enabled": False,
        "allowedSeniority": [],
        "excludedSeniority": [],
        "targetTechnologies": [],
        "excludedTechnologies": [],
    }
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(JobFilterSettingsRecord)) == 0


def test_put_job_filter_settings_upserts_normalized_owner_scoped_resource() -> None:
    client, sessions = job_filter_client()
    owner_a = {"X-Rufina-Owner-Id": "owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "owner-b"}

    try:
        created = client.put(
            "/job-search/filter-settings",
            headers=owner_a,
            json={
                "schemaVersion": 1,
                "enabled": True,
                "seniorityEnabled": False,
                "allowedSeniority": ["mid", "senior", "mid"],
                "excludedSeniority": ["director"],
                "postingAgeEnabled": True,
                "maxPostingAgeDays": 7,
                "technologyStackEnabled": True,
                "targetTechnologies": [" Python ", "python", "FastAPI"],
                "excludedTechnologies": [" C# ", ".NET"],
            },
        )
        other_owner = client.get(
            "/job-search/filter-settings",
            headers=owner_b,
        )
        replaced = client.put(
            "/job-search/filter-settings",
            headers=owner_a,
            json={"schemaVersion": 1, "enabled": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 200
    assert created.json() == {
        "schemaVersion": 1,
        "enabled": True,
        "seniorityEnabled": False,
        "allowedSeniority": ["mid", "senior"],
        "excludedSeniority": ["director"],
        "postingAgeEnabled": True,
        "maxPostingAgeDays": 7,
        "technologyStackEnabled": True,
        "targetTechnologies": ["Python", "FastAPI"],
        "excludedTechnologies": ["C#", ".NET"],
        "updatedAt": created.json()["updatedAt"],
    }
    assert other_owner.status_code == 200
    assert other_owner.json()["enabled"] is False
    assert "updatedAt" not in other_owner.json()
    assert replaced.status_code == 200
    assert replaced.json()["enabled"] is False
    assert replaced.json()["allowedSeniority"] == []
    assert replaced.json()["targetTechnologies"] == []

    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(JobFilterSettingsRecord)) == 1
        record = db.get(JobFilterSettingsRecord, "owner-a")
        assert record is not None
        assert record.data == {
            "schemaVersion": 1,
            "enabled": False,
            "allowedSeniority": [],
            "excludedSeniority": [],
            "targetTechnologies": [],
            "excludedTechnologies": [],
        }


def test_put_job_filter_settings_rejects_conflicts_without_overwriting() -> None:
    client, sessions = job_filter_client()
    headers = {"X-Rufina-Owner-Id": "validation-owner"}

    try:
        valid = client.put(
            "/job-search/filter-settings",
            headers=headers,
            json={
                "enabled": True,
                "targetTechnologies": ["Python"],
            },
        )
        invalid = client.put(
            "/job-search/filter-settings",
            headers=headers,
            json={
                "enabled": True,
                "targetTechnologies": ["Python"],
                "excludedTechnologies": ["python"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert valid.status_code == 200
    assert invalid.status_code == 422
    with sessions() as db:
        record = db.get(JobFilterSettingsRecord, "validation-owner")
        assert record is not None
        assert record.data["targetTechnologies"] == ["Python"]
        assert record.data["excludedTechnologies"] == []
