import hashlib
from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.profile import (
    ImportedExperienceEntry,
    ProfileFileRecord,
    ProfilePayload,
    ProfileRecord,
)
from app.services.ai_privacy import record_ai_activity
from app.services.profile_files import enrich_profile_with_files, list_profile_files

OWNER_A = {"X-Rufina-Owner-Id": "profile-file-owner-a"}
OWNER_B = {"X-Rufina-Owner-Id": "profile-file-owner-b"}
PDF_BYTES = b"%PDF-1.4\nprofile-file-test\n%%EOF"
PNG_BYTES = b"\x89PNG\r\n\x1a\nprofile-file-test"


@pytest.fixture
def api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[record_ai_activity] = lambda: None
    monkeypatch.setattr(
        "app.api.profile.best_effort_extracted_text",
        lambda **_kwargs: "",
    )
    try:
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(record_ai_activity, None)
        app.dependency_overrides.pop(get_settings, None)
        engine.dispose()


def upload_file(
    client: TestClient,
    *,
    owner: dict[str, str] = OWNER_A,
    kind: str = "supporting_document",
    file_name: str = "evidence.pdf",
    content_type: str = "application/pdf",
    content: bytes = PDF_BYTES,
    **metadata: str,
):
    return client.post(
        "/profile/files",
        params={"kind": kind, "file_name": file_name, **metadata},
        content=content,
        headers={**owner, "Content-Type": content_type},
    )


def test_profile_file_lifecycle_uses_metadata_only_payload_and_private_download(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api_client

    uploaded = upload_file(
        client,
        file_name="../Résumé evidence.pdf",
        title="Reference",
        category="Certificate",
        language="English",
        issuer="Rufina Labs",
        notes="Verified evidence",
    )

    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert payload == {
        "id": payload["id"],
        "kind": "supporting_document",
        "title": "Reference",
        "category": "Certificate",
        "language": "English",
        "issuer": "Rufina Labs",
        "notes": "Verified evidence",
        "fileName": "Résumé evidence.pdf",
        "sizeBytes": len(PDF_BYTES),
        "contentType": "application/pdf",
        "contentSha256": hashlib.sha256(PDF_BYTES).hexdigest(),
        "extractedTextAvailable": False,
        "createdAt": payload["createdAt"],
        "updatedAt": payload["updatedAt"],
        "downloadUrl": f"/profile/files/{payload['id']}",
    }
    assert "content" not in payload
    assert "dataUrl" not in payload
    assert uploaded.headers["cache-control"] == "private, no-store"
    assert uploaded.headers["cross-origin-resource-policy"] == "same-site"
    assert uploaded.headers["x-content-type-options"] == "nosniff"
    assert uploaded.headers["location"] == payload["downloadUrl"]

    listed = client.get("/profile/files", headers=OWNER_A)
    assert listed.status_code == 200
    assert listed.json() == [payload]
    assert listed.headers["cache-control"] == "private, no-store"

    patched = client.patch(
        payload["downloadUrl"],
        headers=OWNER_A,
        json={"title": "Updated reference", "notes": "Updated only"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Updated reference"
    assert patched.json()["notes"] == "Updated only"
    assert patched.json()["contentSha256"] == payload["contentSha256"]

    downloaded = client.get(payload["downloadUrl"], headers=OWNER_A)
    assert downloaded.status_code == 200
    assert downloaded.content == PDF_BYTES
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["cross-origin-resource-policy"] == "same-site"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "attachment;" in downloaded.headers["content-disposition"]
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]

    with sessions() as db:
        stored = db.get(ProfileFileRecord, payload["id"])
        assert stored is not None
        assert stored.content == PDF_BYTES
        assert stored.owner_id == "profile-file-owner-a"
        assert stored.title == "Updated reference"

        db.expunge_all()
        listed_records = list_profile_files(db)
        listed_record, has_extracted_text = listed_records[0]
        assert has_extracted_text is False
        assert {"content", "extracted_text"} <= sa_inspect(listed_record).unloaded

    deleted = client.delete(payload["downloadUrl"], headers=OWNER_A)
    assert deleted.status_code == 204
    assert client.get(payload["downloadUrl"], headers=OWNER_A).status_code == 404
    assert client.delete(payload["downloadUrl"], headers=OWNER_A).status_code == 404


def test_ai_profile_hydration_does_not_load_empty_resume_binary(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api_client
    uploaded = upload_file(
        client,
        kind="primary_resume",
        file_name="resume.pdf",
    )
    assert uploaded.status_code == 201

    with sessions() as db:
        db.expunge_all()
        profile = enrich_profile_with_files(db, ProfilePayload())
        record = db.scalar(
            select(ProfileFileRecord).where(ProfileFileRecord.id == uploaded.json()["id"])
        )
        assert record is not None
        assert profile.runtime_primary_resume is not None
        assert profile.runtime_primary_resume["extracted_text"] == ""
        assert "content" in sa_inspect(record).unloaded


def test_profile_files_are_owner_scoped_and_singletons_are_replaced(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api_client
    first = upload_file(
        client,
        kind="avatar",
        file_name="first.png",
        content_type="image/png",
        content=PNG_BYTES,
    )
    replacement_bytes = b"\x89PNG\r\n\x1a\nreplacement"
    replacement = upload_file(
        client,
        kind="avatar",
        file_name="second.png",
        content_type="image/png",
        content=replacement_bytes,
    )

    assert first.status_code == replacement.status_code == 201
    assert first.json()["id"] != replacement.json()["id"]
    assert client.get(first.json()["downloadUrl"], headers=OWNER_A).status_code == 404
    assert client.get("/profile/files", headers=OWNER_A).json() == [replacement.json()]
    assert client.get("/profile/files", headers=OWNER_B).json() == []
    assert client.get(replacement.json()["downloadUrl"], headers=OWNER_B).status_code == 404
    assert client.delete(replacement.json()["downloadUrl"], headers=OWNER_B).status_code == 404


def test_uploads_do_not_overwrite_singletons_and_allow_duplicate_supporting_files(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api_client
    avatar = upload_file(
        client,
        kind="avatar",
        file_name="current.png",
        content_type="image/png",
        content=PNG_BYTES,
    )
    blocked_avatar = client.post(
        "/profile/files",
        params={
            "kind": "avatar",
            "file_name": "legacy.png",
            "replaceExisting": "false",
        },
        content=b"\x89PNG\r\n\x1a\nlegacy-avatar",
        headers={**OWNER_A, "Content-Type": "image/png"},
    )

    first = client.post(
        "/profile/files",
        params={
            "kind": "supporting_document",
            "file_name": "first.pdf",
            "title": "First metadata",
        },
        content=PDF_BYTES,
        headers={**OWNER_A, "Content-Type": "application/pdf"},
    )
    second = client.post(
        "/profile/files",
        params={
            "kind": "supporting_document",
            "file_name": "second.pdf",
            "title": "Second metadata",
        },
        content=PDF_BYTES,
        headers={**OWNER_A, "Content-Type": "application/pdf"},
    )
    assert avatar.status_code == 201
    assert blocked_avatar.status_code == 412
    downloaded_avatar = client.get(avatar.json()["downloadUrl"], headers=OWNER_A)
    assert downloaded_avatar.status_code == 200
    assert downloaded_avatar.headers["content-disposition"].startswith("inline;")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.parametrize(
    ("file_name", "content_type", "content", "expected_status"),
    [
        ("empty.pdf", "application/pdf", b"", 422),
        ("wrong.pdf", "image/png", PNG_BYTES, 422),
        ("wrong.png", "application/pdf", PDF_BYTES, 422),
        ("fake.pdf", "application/pdf", b"not-a-pdf", 422),
        ("missing.bin", "application/octet-stream", PDF_BYTES, 422),
    ],
)
def test_profile_file_upload_validates_body_mime_and_extension(
    api_client: tuple[TestClient, sessionmaker[Session]],
    file_name: str,
    content_type: str,
    content: bytes,
    expected_status: int,
) -> None:
    client, _sessions = api_client
    response = upload_file(
        client,
        file_name=file_name,
        content_type=content_type,
        content=content,
    )
    assert response.status_code == expected_status


def test_profile_file_upload_enforces_kind_limit(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api_client
    response = upload_file(
        client,
        kind="avatar",
        file_name="large.png",
        content_type="image/png",
        content=b"\x89PNG\r\n\x1a\n" + (b"x" * 1_000_000),
    )
    assert response.status_code == 413


def test_profile_file_upload_infers_safe_octet_stream_from_extension_and_signature(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api_client
    response = upload_file(
        client,
        kind="primary_resume",
        file_name="resume.pdf",
        content_type="application/octet-stream",
        content=PDF_BYTES,
    )
    assert response.status_code == 201
    assert response.json()["contentType"] == "application/pdf"


def test_profile_update_rejects_legacy_file_bytes_and_data_avatar(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api_client
    response = client.put(
        "/profile",
        headers=OWNER_A,
        json={
            "name": "Ada Lovelace",
            "avatar_url": "data:image/png;base64,secret-avatar",
            "documents": '[{"data_url":"data:application/pdf;base64,secret"}]',
            "resume_data_url": "data:application/pdf;base64,secret-resume",
            "resume_file_name": "resume.pdf",
        },
    )

    assert response.status_code == 422
    with sessions() as db:
        record = db.scalar(
            select(ProfileRecord).where(ProfileRecord.owner_id == "profile-file-owner-a")
        )
        assert record is None


def test_resume_import_reads_owner_scoped_profile_file(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _sessions = api_client
    uploaded = upload_file(
        client,
        kind="primary_resume",
        file_name="resume.pdf",
    )
    assert uploaded.status_code == 201
    resume_id = uploaded.json()["id"]
    captured: list[str] = []

    monkeypatch.setattr(
        "app.api.profile.extract_profile_resume_source",
        lambda record: SimpleNamespace(text=f"stored:{record.content.decode(errors='ignore')}"),
    )
    monkeypatch.setattr(
        "app.api.profile.parse_resume_experience_with_selected_backend",
        lambda text, _settings: (
            captured.append(text) or [ImportedExperienceEntry(title="Engineer", company="Rufina")]
        ),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)

    imported = client.post(
        "/profile/import-experience-from-resume",
        headers=OWNER_A,
        json={"profile_file_id": resume_id},
    )
    foreign = client.post(
        "/profile/import-experience-from-resume",
        headers=OWNER_B,
        json={"profileFileId": resume_id},
    )

    assert imported.status_code == 200
    assert imported.json()["experience"][0]["title"] == "Engineer"
    assert captured == [f"stored:{PDF_BYTES.decode()}"]
    assert foreign.status_code == 404


def test_primary_resume_metadata_patch_is_rejected(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _sessions = api_client
    uploaded = upload_file(
        client,
        kind="primary_resume",
        file_name="resume.pdf",
    )
    response = client.patch(
        uploaded.json()["downloadUrl"],
        headers=OWNER_A,
        json={"title": "Changed"},
    )
    assert response.status_code == 422
