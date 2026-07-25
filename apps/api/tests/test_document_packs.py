from fastapi.testclient import TestClient

from app.main import app


PACK_ITEM = {
    "title": "Legacy tailored resume",
    "generationArtifactId": "legacy-artifact",
}


def test_legacy_resume_pack_preflight_is_gone() -> None:
    response = TestClient(app).post(
        "/documents/packs/validate-resume",
        json={
            "applicationId": "application-1",
            "resume": PACK_ITEM,
        },
    )

    assert response.status_code == 410
    assert "PDF artifact" in response.json()["detail"]


def test_legacy_docx_pack_creation_and_status_are_gone() -> None:
    client = TestClient(app)

    created = client.post(
        "/documents/packs",
        json={
            "packJobId": "legacy-pack",
            "applicationId": "application-1",
            "resume": PACK_ITEM,
        },
    )
    status = client.get(
        "/documents/packs/legacy-pack",
        params={"applicationId": "application-1"},
    )

    assert created.status_code == 410
    assert "Legacy DOCX application packs were removed" in created.json()["detail"]
    assert status.status_code == 410
    assert "Legacy DOCX application packs were removed" in status.json()["detail"]
