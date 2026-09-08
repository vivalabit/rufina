import json
import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.identity import current_owner_id
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.notifications import CriticalNotificationRecord
from app.services.critical_notifications import create_parser_failure_notifications


@pytest.fixture
def notification_api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    settings = Settings(app_env="local", database_url="sqlite://")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_final_parser_failure_creates_one_persistent_critical_notification(
    notification_api: tuple[TestClient, sessionmaker[Session]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, sessions = notification_api
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    owner_token = current_owner_id.set("notification-owner")
    try:
        with sessions() as db:
            first = create_parser_failure_notifications(
                db,
                run_id="run-1",
                source_errors={"sbb": "SBB returned HTTP 503"},
                source_attempts={"sbb": 3},
            )
            db.commit()
            second = create_parser_failure_notifications(
                db,
                run_id="run-1",
                source_errors={"sbb": "SBB returned HTTP 503"},
                source_attempts={"sbb": 3},
            )
            db.commit()

            records = list(db.scalars(select(CriticalNotificationRecord)).all())
    finally:
        current_owner_id.reset(owner_token)

    assert len(first) == 1
    assert len(second) == 1
    assert len(records) == 1
    assert records[0].attempts == 3
    assert records[0].description == "SBB returned HTTP 503"
    events = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"critical_notification.created"' in record.message
    ]
    assert len(events) == 1
    assert events[0]["attempts"] == 3


def test_critical_notifications_are_owner_scoped_and_deleted_only_manually(
    notification_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = notification_api
    with sessions() as db:
        db.add_all(
            [
                CriticalNotificationRecord(
                    id="notice-owner-a",
                    owner_id="owner-a",
                    severity="critical",
                    category="parser_failure",
                    source="sbb",
                    title="SBB parser failed",
                    description="HTTP 503",
                    attempts=3,
                    run_id="run-a",
                ),
                CriticalNotificationRecord(
                    id="notice-owner-b",
                    owner_id="owner-b",
                    severity="critical",
                    category="parser_failure",
                    source="swisscom",
                    title="Swisscom parser failed",
                    description="Request timed out",
                    attempts=3,
                    run_id="run-b",
                ),
            ]
        )
        db.commit()

    owner_a_headers = {"X-Rufina-Owner-Id": "owner-a"}
    response = client.get("/notifications/critical", headers=owner_a_headers)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "notice-owner-a",
            "severity": "critical",
            "category": "parser_failure",
            "source": "sbb",
            "title": "SBB parser failed",
            "description": "HTTP 503",
            "attempts": 3,
            "runId": "run-a",
            "createdAt": response.json()[0]["createdAt"],
        }
    ]
    assert (
        client.delete(
            "/notifications/critical/notice-owner-a",
            headers={"X-Rufina-Owner-Id": "owner-b"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            "/notifications/critical/notice-owner-a",
            headers=owner_a_headers,
        ).status_code
        == 204
    )
    assert (
        client.get(
            "/notifications/critical",
            headers=owner_a_headers,
        ).json()
        == []
    )
    assert [
        item["id"]
        for item in client.get(
            "/notifications/critical",
            headers={"X-Rufina-Owner-Id": "owner-b"},
        ).json()
    ] == ["notice-owner-b"]


def test_partial_parser_result_creates_persistent_notification_through_api(
    notification_api,
) -> None:
    from app.models.parsers import ParsedJob, ParserSearchResponse
    from app.services.parser_validation import validate_parser_result

    client, sessions = notification_api
    result = ParserSearchResponse(
        parser="sbb",
        status="completed",
        search_url="https://jobs.sbb.ch",
        jobs=[
            ParsedJob(
                title="Engineer", url="https://jobs.sbb.ch/1", raw={"detail_error": "HTTP 503"}
            )
        ],
    )
    validated, error = validate_parser_result(result)
    assert len(validated.jobs) == 1
    token = current_owner_id.set("partial-owner")
    try:
        with sessions() as db:
            create_parser_failure_notifications(
                db, run_id="partial-run", source_errors={"sbb": error}, source_attempts={"sbb": 1}
            )
            db.commit()
    finally:
        current_owner_id.reset(token)
    headers = {"X-Rufina-Owner-Id": "partial-owner"}
    response = client.get("/notifications/critical", headers=headers)
    assert response.status_code == 200
    notice = response.json()[0]
    assert notice["category"] == "parser_partial"
    assert notice["title"] == "SBB CFF FFS parser returned partial results"
    assert "HTTP 503" in notice["description"]
    assert notice["attempts"] == 1
    assert client.get("/notifications/critical", headers=headers).json()[0]["id"] == notice["id"]
    assert (
        client.delete(f"/notifications/critical/{notice['id']}", headers=headers).status_code == 204
    )
