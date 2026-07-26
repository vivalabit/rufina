from collections.abc import Generator
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.documents import (
    DocumentFileRecord,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.services.resume_template_preview import preview_rate_limiter


OWNER_A = {"X-Rufina-Owner-Id": "owner-a"}
OWNER_B = {"X-Rufina-Owner-Id": "owner-b"}


@pytest.fixture
def api_sessions() -> Generator[sessionmaker[Session], None, None]:
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
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture
def client(api_sessions: sessionmaker[Session]) -> TestClient:
    del api_sessions
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_preview_rate_limit() -> Generator[None, None, None]:
    preview_rate_limiter.reset()
    try:
        yield
    finally:
        preview_rate_limiter.reset()


def template_request(name: str = "Zurich backend") -> dict[str, object]:
    return {
        "name": name,
        "baseTemplateId": "modern_two_column",
        "designJson": {
            "accentColor": "#176B87",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "compact",
            "pageMargins": {
                "top": 12,
                "right": 12,
                "bottom": 12,
                "left": 12,
            },
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 32,
            "sidebarSections": ["skills", "languages"],
        },
    }


def create_custom_template(
    client: TestClient,
    *,
    headers: dict[str, str] = OWNER_A,
    name: str = "Zurich backend",
) -> dict[str, object]:
    response = client.post(
        "/resume-templates",
        headers=headers,
        json=template_request(name),
    )
    assert response.status_code == 201
    return response.json()


def test_lists_bundled_and_owner_custom_templates_through_both_routes(
    client: TestClient,
) -> None:
    custom = create_custom_template(client)

    primary = client.get("/resume-templates", headers=OWNER_A)
    alias = client.get("/documents/resume-templates", headers=OWNER_A)
    other_owner = client.get("/resume-templates", headers=OWNER_B)

    assert primary.status_code == 200
    assert alias.status_code == 200
    assert alias.json() == primary.json()
    assert [item["kind"] for item in primary.json()] == [
        "bundled",
        "bundled",
        "bundled",
        "custom",
    ]
    assert primary.json()[-1]["id"] == custom["id"]
    assert all(item["kind"] == "bundled" for item in other_owner.json())
    assert all("ownerId" not in item for item in primary.json())
    assert all("path" not in key.lower() for item in primary.json() for key in item)


def test_custom_template_crud_is_owner_scoped(client: TestClient) -> None:
    created = create_custom_template(client)
    template_id = created["id"]
    original_hash = created["contentSha256"]

    own_detail = client.get(f"/resume-templates/{template_id}", headers=OWNER_A)
    foreign_detail = client.get(f"/resume-templates/{template_id}", headers=OWNER_B)
    foreign_update = client.patch(
        f"/resume-templates/{template_id}",
        headers=OWNER_B,
        json={"name": "Stolen"},
    )
    updated = client.patch(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
        json={"name": "Senior backend"},
    )

    assert own_detail.status_code == 200
    assert foreign_detail.status_code == 404
    assert foreign_update.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["name"] == "Senior backend"
    assert updated.json()["version"] == 2
    assert updated.json()["contentSha256"] == original_hash

    foreign_delete = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_B,
    )
    deleted = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
    )
    missing = client.get(f"/resume-templates/{template_id}", headers=OWNER_A)

    assert foreign_delete.status_code == 404
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_bundled_templates_are_read_only_but_can_be_duplicated(
    client: TestClient,
) -> None:
    detail = client.get("/resume-templates/modern_single", headers=OWNER_A)
    updated = client.patch(
        "/resume-templates/modern_single",
        headers=OWNER_A,
        json={"name": "Changed"},
    )
    deleted = client.delete(
        "/resume-templates/modern_single",
        headers=OWNER_A,
    )
    duplicated = client.post(
        "/resume-templates/modern_single/duplicate",
        headers=OWNER_A,
    )

    assert detail.status_code == 200
    assert detail.json()["kind"] == "bundled"
    assert updated.status_code == 405
    assert deleted.status_code == 405
    assert duplicated.status_code == 201
    assert duplicated.json()["kind"] == "custom"
    assert duplicated.json()["baseTemplateId"] == "modern_single"
    assert duplicated.json()["name"] == "Modern copy"


def test_custom_template_duplicate_requires_ownership(client: TestClient) -> None:
    created = create_custom_template(client)
    template_id = created["id"]

    foreign = client.post(
        f"/resume-templates/{template_id}/duplicate",
        headers=OWNER_B,
        json={"name": "Foreign copy"},
    )
    duplicated = client.post(
        f"/resume-templates/{template_id}/duplicate",
        headers=OWNER_A,
        json={"name": "Application copy"},
    )

    assert foreign.status_code == 404
    assert duplicated.status_code == 201
    assert duplicated.json()["name"] == "Application copy"
    assert duplicated.json()["version"] == 1
    assert duplicated.json()["contentSha256"] == created["contentSha256"]


def test_custom_template_export_is_portable_and_import_revalidates(
    client: TestClient,
) -> None:
    created = create_custom_template(
        client,
        headers=OWNER_A,
        name="My Swiss CV",
    )

    exported = client.get(
        f"/resume-templates/{created['id']}/export",
        headers=OWNER_A,
    )
    foreign_export = client.get(
        f"/resume-templates/{created['id']}/export",
        headers=OWNER_B,
    )

    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "no-store"
    assert exported.headers["x-content-type-options"] == "nosniff"
    assert exported.headers["content-disposition"] == (
        'attachment; filename="My-Swiss-CV.resume-template.local.json"'
    )
    backup = exported.json()
    assert set(backup) == {
        "format",
        "schemaVersion",
        "name",
        "baseTemplateId",
        "designJson",
    }
    assert backup["format"] == "rufina.resume-template"
    assert backup["schemaVersion"] == 1
    assert backup["name"] == "My Swiss CV"
    assert backup["baseTemplateId"] == "modern_two_column"
    assert "id" not in backup
    assert "ownerId" not in backup
    assert "contentSha256" not in backup
    assert "createdAt" not in backup
    assert "updatedAt" not in backup
    assert foreign_export.status_code == 404

    imported = client.post(
        "/resume-templates/import",
        headers=OWNER_B,
        json=backup,
    )

    assert imported.status_code == 201
    assert imported.json()["kind"] == "custom"
    assert imported.json()["name"] == created["name"]
    assert imported.json()["designJson"] == created["designJson"]
    assert imported.json()["id"] != created["id"]
    assert (
        client.get(
            f"/resume-templates/{imported.json()['id']}",
            headers=OWNER_A,
        ).status_code
        == 404
    )


def test_import_rejects_internal_fields_and_invalid_design_tokens(
    client: TestClient,
) -> None:
    created = create_custom_template(client)
    backup = client.get(
        f"/resume-templates/{created['id']}/export",
        headers=OWNER_A,
    ).json()

    with_internal_fields = client.post(
        "/resume-templates/import",
        headers=OWNER_A,
        json={
            **backup,
            "id": created["id"],
            "ownerId": "owner-a",
        },
    )
    invalid_design = client.post(
        "/resume-templates/import",
        headers=OWNER_A,
        json={
            **backup,
            "designJson": {
                **backup["designJson"],
                "accentColor": "url(file:///private/template.css)",
            },
        },
    )
    bundled_export = client.get(
        "/resume-templates/modern_single/export",
        headers=OWNER_A,
    )

    assert with_internal_fields.status_code == 422
    assert invalid_design.status_code == 422
    assert bundled_export.status_code == 405


def test_delete_is_blocked_after_template_was_used_for_pdf(
    client: TestClient,
    api_sessions: sessionmaker[Session],
) -> None:
    created = create_custom_template(client)
    template_id = str(created["id"])
    now = datetime.now(UTC)
    document = DocumentRecord(
        id="custom-template-document",
        owner_id="owner-a",
        type="tailored_resume",
        title="Rendered resume",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    document.versions.append(
        DocumentVersionRecord(
            id="custom-template-version",
            document_id=document.id,
            version=1,
            content="{}",
            created_at=now,
        )
    )
    document.files.append(
        DocumentFileRecord(
            id="custom-template-pdf",
            document_id=document.id,
            version=1,
            file_name="resume.pdf",
            content_type="application/pdf",
            renderer_template_id=template_id,
            renderer_template_version="1",
            content=b"%PDF-1.4",
            created_at=now,
        )
    )
    with api_sessions() as db:
        db.add(document)
        db.commit()

    response = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
    )

    assert response.status_code == 409
    assert "used to render a PDF" in response.json()["detail"]
    assert client.get(f"/resume-templates/{template_id}", headers=OWNER_A).status_code == 200


def test_create_rejects_unknown_design_fields_and_empty_patch(
    client: TestClient,
) -> None:
    invalid_request = template_request()
    design = dict(invalid_request["designJson"])
    design["filesystemPath"] = "/tmp/private-template"
    invalid_request["designJson"] = design

    invalid = client.post(
        "/resume-templates",
        headers=OWNER_A,
        json=invalid_request,
    )
    created = create_custom_template(client)
    empty_patch = client.patch(
        f"/resume-templates/{created['id']}",
        headers=OWNER_A,
        json={},
    )

    assert invalid.status_code == 422
    assert empty_patch.status_code == 422


def test_draft_preview_uses_demo_resume_and_does_not_persist(
    client: TestClient,
    api_sessions: sessionmaker[Session],
) -> None:
    request = template_request()
    request.pop("name")

    response = client.post(
        "/resume-templates/preview",
        headers={**OWNER_A, "Origin": "http://localhost:3000"},
        json=request,
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == (
        'inline; filename="resume-template-preview.pdf"'
    )
    assert response.headers["x-rufina-template-id"] == "preview"
    assert response.headers["x-rufina-template-version"].startswith("draft-")
    assert len(response.headers["x-rufina-design-sha256"]) == 64
    assert "x-rufina-document-id" not in response.headers
    exposed = response.headers["access-control-expose-headers"].casefold()
    assert "x-rufina-design-sha256" in exposed

    reader = PdfReader(BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Jordan Lee" in text
    assert reader.metadata["/ResumeTemplateId"] == "preview"

    with api_sessions() as db:
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentFileRecord)) == 0


def test_saved_preview_is_owner_scoped_and_does_not_create_artifacts(
    client: TestClient,
    api_sessions: sessionmaker[Session],
) -> None:
    custom = create_custom_template(
        client,
        headers=OWNER_A,
        name="Preview template",
    )
    template_id = custom["id"]

    response = client.post(
        f"/resume-templates/{template_id}/preview",
        headers=OWNER_A,
    )
    foreign = client.post(
        f"/resume-templates/{template_id}/preview",
        headers=OWNER_B,
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["x-rufina-template-id"] == template_id
    assert response.headers["x-rufina-template-version"] == "1"
    assert foreign.status_code == 404
    with api_sessions() as db:
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentFileRecord)) == 0


def test_preview_payload_limit_is_checked_before_render(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        resume_template_preview_max_payload_bytes=512,
    )
    request = template_request()
    request.pop("name")
    request["unexpectedPadding"] = "x" * 1_000

    response = client.post(
        "/resume-templates/preview",
        headers=OWNER_A,
        json=request,
    )

    assert response.status_code == 413
    assert "exceeds 512 bytes" in response.json()["detail"]


def test_preview_rate_limit_is_owner_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        resume_template_preview_rate_limit=1,
        resume_template_preview_rate_window_seconds=60,
    )
    monkeypatch.setattr(
        "app.api.resume_templates.render_resume_template_preview",
        lambda _template: b"%PDF-1.7\npreview",
    )

    first = client.post(
        "/resume-templates/classic_single/preview",
        headers=OWNER_A,
    )
    limited = client.post(
        "/resume-templates/classic_single/preview",
        headers=OWNER_A,
    )
    other_owner = client.post(
        "/resume-templates/classic_single/preview",
        headers=OWNER_B,
    )

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert other_owner.status_code == 200


def test_draft_preview_accepts_no_resume_content(client: TestClient) -> None:
    request = template_request()
    request.pop("name")
    request["finalResume"] = {"basics": {"fullName": "User-controlled preview content"}}

    response = client.post(
        "/resume-templates/preview",
        headers=OWNER_A,
        json=request,
    )

    assert response.status_code == 422
