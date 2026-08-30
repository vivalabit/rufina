from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.profile import ProfileRecord, ProfileVersionRecord
from app.services.profile_versions import (
    StaleProfileRevisionError,
    update_profile_data,
)


def test_profile_can_be_updated_and_read() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "avatar_url": "/avatars/default-pug.png",
            "name": "Eduard Ishchenko",
            "current_role": "Frontend Engineer",
            "desired_role": "Product Engineer",
            "location": "Zurich, Switzerland",
            "work_format": "Remote / hybrid",
            "headline": "Builds polished product interfaces and pragmatic AI workflows.",
            "linkedin": "linkedin.com/in/eduard",
            "github": "github.com/eduard",
            "portfolio": "eduard.dev",
            "personal_site": "ishchenko.dev",
            "experience": "Built Rufina profile onboarding",
            "skills": "React\nFastAPI\nProduct engineering",
            "education": "Computer Science",
            "job_preferences": "Remote or hybrid\nProduct-focused teams",
            "dealbreakers": "No unpaid roles",
            "additional_notes": "Prefers pragmatic AI workflows.",
            "documents": "",
            "resume_file_name": "Eduard_Ishchenko_Resume.pdf",
            "resume_file_size": "128 KB",
            "resume_updated_at": "2026-07-04T10:00:00.000Z",
        }

        update_response = client.put("/profile", json=payload)
        read_response = client.get("/profile")
        expected_payload = {key: value for key, value in payload.items() if key != "documents"}

        assert update_response.status_code == 200
        assert update_response.headers["etag"] == '"1"'
        assert update_response.json() == expected_payload
        assert read_response.status_code == 200
        assert read_response.headers["etag"] == '"1"'
        assert read_response.json() == expected_payload

        with testing_session_local() as db:
            stored_profile = db.get(ProfileRecord, "default")
            assert stored_profile is not None
            assert stored_profile.data["name"] == "Eduard Ishchenko"
            assert "documents" not in stored_profile.data
            assert "resume_data_url" not in stored_profile.data
            assert stored_profile.revision == 1
    finally:
        app.dependency_overrides.clear()


def test_sparse_profile_update_cannot_erase_a_complete_profile() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session_local() as db:
        db.add(
            ProfileRecord(
                id="default",
                data={
                    "name": "Eduard Ishchenko",
                    "current_role": "Web Developer",
                    "desired_role": "AI Engineer",
                    "headline": "Python developer",
                    "skills": "Python\nFastAPI",
                },
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        response = client.put("/profile", json={"headline": "Product designer"})
        forced_response = client.put(
            "/profile?allow_destructive=true",
            json={"headline": "Product designer"},
        )

        with testing_session_local() as db:
            stored_profile = db.get(ProfileRecord, "default")
            versions = db.query(ProfileVersionRecord).all()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert forced_response.status_code == 200
    assert stored_profile is not None
    assert stored_profile.data["headline"] == "Product designer"
    assert stored_profile.data["skills"] == ""
    assert len(versions) == 1
    assert versions[0].data["skills"] == "Python\nFastAPI"
    assert versions[0].revision == 1
    assert stored_profile.revision == 2


def test_profiles_are_owner_scoped_and_reject_stale_etags() -> None:
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

    owner_a = {"X-Rufina-Owner-Id": "profile-owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "profile-owner-b"}
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        created_a = client.put("/profile", headers=owner_a, json={"name": "Alice"})
        created_b = client.put("/profile", headers=owner_b, json={"name": "Bob"})
        read_a = client.get("/profile", headers=owner_a)
        read_b = client.get("/profile", headers=owner_b)
        updated_a = client.put(
            "/profile",
            headers={**owner_a, "If-Match": '"1"'},
            json={"name": "Alice Updated"},
        )
        stale_a = client.put(
            "/profile",
            headers={**owner_a, "If-Match": '"1"'},
            json={"name": "Stale Alice"},
        )
        final_a = client.get("/profile", headers=owner_a)
        final_b = client.get("/profile", headers=owner_b)

        with testing_session_local() as db:
            profiles = db.query(ProfileRecord).order_by(ProfileRecord.owner_id).all()
            versions = db.query(ProfileVersionRecord).all()
    finally:
        app.dependency_overrides.clear()

    assert created_a.status_code == 200
    assert created_b.status_code == 200
    assert created_a.headers["etag"] == '"1"'
    assert created_b.headers["etag"] == '"1"'
    assert read_a.json()["name"] == "Alice"
    assert read_b.json()["name"] == "Bob"
    assert updated_a.status_code == 200
    assert updated_a.headers["etag"] == '"2"'
    assert stale_a.status_code == 412
    assert stale_a.headers["etag"] == '"2"'
    assert final_a.json()["name"] == "Alice Updated"
    assert final_a.headers["etag"] == '"2"'
    assert final_b.json()["name"] == "Bob"
    assert final_b.headers["etag"] == '"1"'
    assert [(profile.owner_id, profile.revision) for profile in profiles] == [
        ("profile-owner-a", 2),
        ("profile-owner-b", 1),
    ]
    assert profiles[0].id != profiles[1].id
    assert len(versions) == 1
    assert versions[0].owner_id == "profile-owner-a"
    assert versions[0].revision == 1


def test_profile_revision_update_is_atomic(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.sqlite'}")
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session_local() as db:
        db.add(ProfileRecord(id="default", data={"name": "Initial"}))
        db.commit()

    with testing_session_local() as first_db, testing_session_local() as stale_db:
        first = first_db.get(ProfileRecord, "default")
        stale = stale_db.get(ProfileRecord, "default")
        assert first is not None
        assert stale is not None

        update_profile_data(
            first_db,
            first,
            data={"name": "First writer"},
            reason="test_first_writer",
        )
        first_db.commit()

        with pytest.raises(StaleProfileRevisionError):
            update_profile_data(
                stale_db,
                stale,
                data={"name": "Stale writer"},
                reason="test_stale_writer",
            )
        stale_db.rollback()

    with testing_session_local() as db:
        stored_profile = db.get(ProfileRecord, "default")
        versions = db.query(ProfileVersionRecord).all()

    assert stored_profile is not None
    assert stored_profile.data["name"] == "First writer"
    assert stored_profile.revision == 2
    assert len(versions) == 1
    assert versions[0].data["name"] == "Initial"
    assert versions[0].revision == 1


def test_default_profile_is_empty_for_new_registration() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.get("/profile")

        assert response.status_code == 200
        assert response.json()["avatar_url"] == "/avatars/default-pug.png"
        assert response.json()["name"] == ""
        assert response.json()["current_role"] == ""
        assert response.json()["experience"] == ""
        assert response.json()["resume_file_name"] == ""
    finally:
        app.dependency_overrides.clear()


def test_legacy_placeholder_profile_is_cleared() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session_local() as db:
        db.add(
            ProfileRecord(
                id="default",
                data={
                    "avatar_url": "/avatars/default-pug.png",
                    "name": "Alex Johnson",
                    "current_role": "Senior Product Designer",
                    "desired_role": "Design Manager",
                    "location": "San Francisco, CA, USA",
                    "work_format": "Remote, open to hybrid",
                    "headline": (
                        "Product designer with 7+ years of experience crafting intuitive B2B and B2C "
                        "digital experiences. Combines user empathy with data-driven design to ship "
                        "impactful products."
                    ),
                    "linkedin": "linkedin.com/in/alexjohnson",
                    "github": "github.com/alexjohnson",
                    "portfolio": "alexjohnson.design",
                    "personal_site": "alexjohnson.com",
                },
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.get("/profile")

        assert response.status_code == 200
        assert response.json()["name"] == ""
        assert response.json()["current_role"] == ""
        assert response.json()["linkedin"] == ""
        assert response.json()["github"] == ""
        assert response.json()["portfolio"] == ""
        assert response.json()["personal_site"] == ""

        with testing_session_local() as db:
            stored_profile = db.get(ProfileRecord, "default")
            assert stored_profile is not None
            assert stored_profile.data["name"] == ""
    finally:
        app.dependency_overrides.clear()


def test_legacy_social_links_are_cleared_from_partially_updated_profile() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session_local() as db:
        db.add(
            ProfileRecord(
                id="default",
                data={
                    "avatar_url": "/avatars/default-pug.png",
                    "name": "Eduard Ishchenko",
                    "current_role": "Python developer",
                    "desired_role": "Design Manager",
                    "location": "",
                    "work_format": "",
                    "headline": "Python developer",
                    "linkedin": "linkedin.com/in/alexjohnson",
                    "github": "github.com/alexjohnson",
                    "portfolio": "alexjohnson.design",
                    "personal_site": "alexjohnson.com",
                },
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.get("/profile")

        assert response.status_code == 200
        assert response.json()["name"] == "Eduard Ishchenko"
        assert response.json()["current_role"] == "Python developer"
        assert response.json()["linkedin"] == ""
        assert response.json()["github"] == ""
        assert response.json()["portfolio"] == ""
        assert response.json()["personal_site"] == ""

        with testing_session_local() as db:
            stored_profile = db.get(ProfileRecord, "default")
            assert stored_profile is not None
            assert stored_profile.data["linkedin"] == ""
            assert stored_profile.data["github"] == ""
            assert stored_profile.data["portfolio"] == ""
            assert stored_profile.data["personal_site"] == ""
    finally:
        app.dependency_overrides.clear()
