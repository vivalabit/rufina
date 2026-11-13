from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from tailoring_fixtures import FakeTailoringBackend, runtime_settings, seed_tailoring_sources

from app.core.database import Base, get_db
from app.main import app
from app.services.generation_worker import run_generation_cycle
from app.services.generation_workflow import GenerationWorkflow

RUNS = "/applications/application-1/generation/runs"


@pytest.fixture
def api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    seed_tailoring_sources(sessions)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _completed_run(client: TestClient, sessions: sessionmaker[Session]) -> dict:
    started = client.post(
        RUNS,
        json={
            "documentTypes": ["tailored_resume"],
            "language": "Auto",
            "formattingParameters": {},
            "userPreferences": "",
            "idempotencyKey": "one-click",
        },
    )
    assert started.status_code == 202, started.text
    backend = FakeTailoringBackend()
    run_generation_cycle(
        settings=runtime_settings(),
        session_factory=sessions,
        workflow_factory=lambda s: GenerationWorkflow(settings=s, backend=backend),
    )
    run = client.get(f"{RUNS}/{started.json()['id']}").json()
    assert run["status"] == "completed", run["error"]
    return run


def test_gallery_lists_templates_and_marks_the_one_in_use(api) -> None:
    client, sessions = api
    run = _completed_run(client, sessions)

    response = client.get(f"{RUNS}/{run['id']}/templates")

    assert response.status_code == 200
    templates = response.json()
    assert templates[0]["id"] == "swiss_classic"
    assert [item["id"] for item in templates if item["selected"]] == ["swiss_classic"]
    assert {item["id"] for item in templates if not item["atsSafe"]} == {"modern_two_column"}
    assert templates[1]["thumbnailUrl"].endswith(
        f"/runs/{run['id']}/templates/{templates[1]['id']}/thumbnail"
    )


def test_second_click_switches_the_template_and_keeps_the_content(api) -> None:
    client, sessions = api
    run = _completed_run(client, sessions)
    first_version = run["result"]["documents"][0]["version"]

    response = client.post(
        f"{RUNS}/{run['id']}/render",
        json={"templateId": "modern_single", "revision": run["revision"]},
    )

    assert response.status_code == 200, response.text
    switched = response.json()
    assert switched["status"] == "completed"
    assert switched["result"]["render"]["templateId"] == "modern_single"
    assert switched["result"]["documents"][0]["version"] == first_version + 1
    assert switched["result"]["tailoring"] == run["result"]["tailoring"]
    assert switched["events"][-1]["kind"] == "render.completed"
    pdfs = [item for item in switched["artifacts"] if item["artifactType"] == "resume_pdf"]
    assert [item["metadata"]["templateId"] for item in pdfs] == ["swiss_classic", "modern_single"]
    selected = [
        item["id"]
        for item in client.get(f"{RUNS}/{run['id']}/templates").json()
        if item["selected"]
    ]
    assert selected == ["modern_single"]

    # The Word version of the current design downloads as an attachment.
    docx = [item for item in switched["artifacts"] if item["artifactType"] == "resume_docx"][-1]
    download = client.get(f"{RUNS}/{run['id']}/artifacts/{docx['id']}")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.content[:2] == b"PK"


def test_template_switch_rejects_stale_revisions_and_unknown_templates(api) -> None:
    client, sessions = api
    run = _completed_run(client, sessions)

    stale = client.post(
        f"{RUNS}/{run['id']}/render",
        json={"templateId": "modern_single", "revision": run["revision"] + 5},
    )
    unknown = client.post(
        f"{RUNS}/{run['id']}/render",
        json={"templateId": "no-such-template", "revision": run["revision"]},
    )

    assert stale.status_code == 412
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "document_template_unsupported"
    assert client.get(f"{RUNS}/{run['id']}").json()["revision"] == run["revision"]


def test_template_switch_needs_a_completed_run(api) -> None:
    client, _ = api
    started = client.post(
        RUNS,
        json={
            "documentTypes": ["tailored_resume"],
            "language": "Auto",
            "formattingParameters": {},
            "userPreferences": "",
            "idempotencyKey": "still-queued",
        },
    ).json()

    response = client.post(
        f"{RUNS}/{started['id']}/render",
        json={"templateId": "modern_single", "revision": started["revision"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "run_not_completed"


def test_template_thumbnail_shows_the_runs_own_resume(api) -> None:
    client, sessions = api
    run = _completed_run(client, sessions)

    first = client.get(f"{RUNS}/{run['id']}/templates/modern_single/thumbnail")
    second = client.get(f"{RUNS}/{run['id']}/templates/modern_single/thumbnail")
    other = client.get(f"{RUNS}/{run['id']}/templates/classic_single/thumbnail")
    missing = client.get(f"{RUNS}/{run['id']}/templates/no-such-template/thumbnail")

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert second.headers["etag"] == first.headers["etag"]
    assert other.headers["etag"] != first.headers["etag"]
    assert missing.status_code == 404
