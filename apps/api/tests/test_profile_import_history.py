from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_resume_master_import import master_resume_payload

from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.profile import ProfileFileRecord, ProfileRecord, ProfileVersionRecord
from app.models.resume import MASTER_RESUME_REVIEW_SECTIONS, MasterResume, ResumeSourceFileRecord
from app.services.ai_privacy import record_ai_activity
from app.services.resume_master_import import MasterResumeImportError, MasterResumeImportOutcome

OWNER = {"X-Rufina-Owner-Id": "history-owner"}
OTHER = {"X-Rufina-Owner-Id": "another-owner"}


@pytest.fixture
def client_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: Settings(openclaw_resume_import_enabled=True)
    app.dependency_overrides[record_ai_activity] = lambda: None
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def docx_bytes():
    document = Document()
    document.add_paragraph("Ada Lovelace")
    document.add_paragraph("Platform engineer building reliable Python services.")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def upload(client, *, filename="source.docx", content=None):
    return client.post(
        f"/profile/imports?file_name={filename}",
        content=content or docx_bytes(),
        headers={
            **OWNER,
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )


def test_import_sources_are_optional_immutable_history_not_primary_attachments(
    client_db, monkeypatch
):
    client, engine = client_db
    saved = client.put(
        "/profile", headers=OWNER, json={"name": "Ada", "additional_notes": "Manually entered"}
    )
    assert saved.status_code == 200
    initial = saved.json()
    assert client.get("/profile/imports", headers=OWNER).json() == []
    content = docx_bytes()
    uploaded = upload(client, content=content)
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()
    assert source["status"] == "pending"
    assert client.get("/profile", headers=OWNER).json() == initial
    assert client.get("/profile/files", headers=OWNER).json() == []
    assert client.get(source["downloadUrl"], headers=OWNER).content == content

    def parsed(extraction, master_id, settings):
        return MasterResumeImportOutcome(
            master_resume=MasterResume.model_validate(master_resume_payload(master_id)),
            model="test",
            backend="openai_api",
        )

    monkeypatch.setattr("app.api.profile_imports.parse_master_resume_with_selected_backend", parsed)
    preview = client.post(f"/profile/imports/{source['id']}/preview", headers=OWNER)
    assert preview.status_code == 200, preview.text
    draft = preview.json()
    response = client.post(
        "/profile/import-master-resume/confirm",
        headers=OWNER,
        json={
            "sourceFileId": source["id"],
            "masterResume": draft["masterResume"],
            "expectedProfileRevision": draft["profileRevision"],
            "confirmedSections": MASTER_RESUME_REVIEW_SECTIONS,
        },
    )
    assert response.status_code == 200, response.text
    history = client.get("/profile/imports", headers=OWNER).json()
    assert history == [{**source, "status": "imported", "canReview": False, "profileVersion": 2}]
    assert client.get("/profile", headers=OWNER).json()["additional_notes"] == "Manually entered"
    assert client.get(source["downloadUrl"], headers=OWNER).content == content
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ProfileFileRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ProfileVersionRecord)) == 2
        original = db.get(ResumeSourceFileRecord, source["id"])
        assert original.content == content
        assert db.scalar(select(ProfileRecord)).data["sources"][0]["source_file_id"] == source["id"]
    assert client.post(f"/profile/imports/{source['id']}/preview", headers=OWNER).status_code == 409


def test_failed_import_and_later_upload_keep_original_source_and_owner_isolation(
    client_db, monkeypatch
):
    client, _ = client_db
    content = docx_bytes()
    first = upload(client, content=content).json()

    def unavailable(*args):
        raise MasterResumeImportError("AI offline")

    monkeypatch.setattr(
        "app.api.profile_imports.parse_master_resume_with_selected_backend", unavailable
    )
    assert client.post(f"/profile/imports/{first['id']}/preview", headers=OWNER).status_code == 503
    second = upload(client, filename="other.docx").json()
    assert second["id"] != first["id"]
    history = client.get("/profile/imports", headers=OWNER).json()
    assert len(history) == 2
    assert all(source["canReview"] for source in history)
    assert client.get(first["downloadUrl"], headers=OWNER).content == content
    assert client.get("/profile/imports", headers=OTHER).json() == []
    assert client.get(first["downloadUrl"], headers=OTHER).status_code == 404
    assert client.post(f"/profile/imports/{first['id']}/preview", headers=OTHER).status_code == 404


def test_invalid_uploads_do_not_create_sources(client_db):
    client, _ = client_db
    assert upload(client, content=b"invalid DOCX").status_code == 422
    assert client.get("/profile/imports", headers=OWNER).json() == []


def test_legacy_attachment_remains_in_history_without_becoming_required(client_db):
    client, _ = client_db
    content = docx_bytes()
    uploaded = client.post(
        "/profile/files?kind=primary_resume&file_name=legacy.docx",
        content=content,
        headers={
            **OWNER,
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
    assert uploaded.status_code == 201
    source = client.get("/profile/imports", headers=OWNER).json()[0]
    assert source["status"] == "stored"
    assert source["canReview"] is False
    assert client.get(source["downloadUrl"], headers=OWNER).content == content
    assert client.get("/profile/imports", headers=OTHER).json() == []


def test_extraction_failure_keeps_original_downloadable(client_db, monkeypatch):
    from app.services.resume_source_extraction import ResumeSourceExtractionError

    client, _ = client_db

    def fail_extraction(**kwargs):
        raise ResumeSourceExtractionError("No readable text")

    monkeypatch.setattr("app.api.profile_imports.extract_resume_source", fail_extraction)
    content = docx_bytes()
    uploaded = upload(client, content=content)
    assert uploaded.status_code == 201
    source = uploaded.json()
    assert source["status"] == "stored"
    assert source["canReview"] is False
    assert client.get(source["downloadUrl"], headers=OWNER).content == content
