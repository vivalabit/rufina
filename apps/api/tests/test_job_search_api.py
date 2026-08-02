from collections.abc import Generator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import job_search as job_search_api
from app.core.database import Base, get_db
from app.main import app


def test_job_search_config_and_schedule_crud_is_owner_scoped(
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    now = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(job_search_api, "utc_now", lambda: now)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    owner_a = {"X-Rufina-Owner-Id": "owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "owner-b"}

    try:
        create_config = client.post(
            "/job-search/configs",
            headers=owner_a,
            json={
                "name": " Zurich product roles ",
                "filters": {"keywords": "Product Manager", "location": "Zurich"},
            },
        )
        assert create_config.status_code == 201
        config = create_config.json()
        config_id = config["id"]
        assert config["name"] == "Zurich product roles"
        assert config["filters"] == {
            "keywords": "Product Manager",
            "location": "Zurich",
        }

        assert (
            client.get(
                f"/job-search/configs/{config_id}",
                headers=owner_b,
            ).status_code
            == 404
        )
        assert client.get("/job-search/configs", headers=owner_b).json() == []
        assert (
            client.post(
                "/job-search/schedules",
                headers=owner_b,
                json=schedule_request(config_id=config_id, name="Foreign config"),
            ).status_code
            == 404
        )

        update_config = client.patch(
            f"/job-search/configs/{config_id}",
            headers=owner_a,
            json={"name": "Zurich PM roles"},
        )
        assert update_config.status_code == 200
        assert update_config.json()["name"] == "Zurich PM roles"

        invalid_source = client.post(
            "/job-search/schedules",
            headers=owner_a,
            json={
                **schedule_request(config_id=config_id, name="Invalid source"),
                "sources": ["monster"],
            },
        )
        assert invalid_source.status_code == 422
        invalid_days = client.post(
            "/job-search/schedules",
            headers=owner_a,
            json={
                **schedule_request(config_id=config_id, name="Invalid days"),
                "weekdays": [],
            },
        )
        assert invalid_days.status_code == 422

        first_schedule = client.post(
            "/job-search/schedules",
            headers=owner_a,
            json=schedule_request(config_id=config_id, name="Morning search"),
        )
        second_schedule = client.post(
            "/job-search/schedules",
            headers=owner_a,
            json=schedule_request(config_id=config_id, name="Second search"),
        )
        assert first_schedule.status_code == 201
        assert second_schedule.status_code == 201
        first = first_schedule.json()
        first_id = first["id"]
        second_id = second_schedule.json()["id"]
        assert first["configId"] == config_id
        assert first["sources"] == ["linkedin", "indeed", "jobs_ch"]
        assert parse_datetime(first["nextRunAt"]) == datetime(
            2026,
            7,
            20,
            5,
            30,
            tzinfo=UTC,
        )
        assert len(client.get("/job-search/schedules", headers=owner_a).json()) == 2
        assert (
            client.get(
                f"/job-search/schedules/{first_id}",
                headers=owner_b,
            ).status_code
            == 404
        )

        blocked_delete = client.delete(
            f"/job-search/configs/{config_id}",
            headers=owner_a,
        )
        assert blocked_delete.status_code == 409
        assert blocked_delete.json()["detail"] == "Config is used by one or more schedules"

        changed_time = client.patch(
            f"/job-search/schedules/{first_id}",
            headers=owner_a,
            json={"localTime": "08:30:00"},
        )
        assert parse_datetime(changed_time.json()["nextRunAt"]) == datetime(
            2026,
            7,
            20,
            6,
            30,
            tzinfo=UTC,
        )
        changed_timezone = client.patch(
            f"/job-search/schedules/{first_id}",
            headers=owner_a,
            json={"timezone": "UTC"},
        )
        assert parse_datetime(changed_timezone.json()["nextRunAt"]) == datetime(
            2026,
            7,
            20,
            8,
            30,
            tzinfo=UTC,
        )
        changed_days = client.patch(
            f"/job-search/schedules/{first_id}",
            headers=owner_a,
            json={"weekdays": [1]},
        )
        assert parse_datetime(changed_days.json()["nextRunAt"]) == datetime(
            2026,
            7,
            21,
            8,
            30,
            tzinfo=UTC,
        )

        disabled = client.patch(
            f"/job-search/schedules/{first_id}",
            headers=owner_a,
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["nextRunAt"] is None

        assert (
            client.delete(
                f"/job-search/schedules/{first_id}",
                headers=owner_a,
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/job-search/schedules/{second_id}",
                headers=owner_a,
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/job-search/configs/{config_id}",
                headers=owner_a,
            ).status_code
            == 204
        )
        assert client.get("/job-search/configs", headers=owner_a).json() == []
    finally:
        app.dependency_overrides.clear()


def test_source_configs_and_presets_keep_queries_separate_by_source() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    headers = {"X-Rufina-Owner-Id": "source-config-owner"}
    other_owner = {"X-Rufina-Owner-Id": "other-owner"}

    try:
        profile = client.post(
            "/job-search/configs",
            headers=headers,
            json={
                "name": "Entry IT",
                "filters": {
                    "schemaVersion": 2,
                    "search": {"keywords": "entry software"},
                    "screening": {"enabled": True},
                },
            },
        ).json()
        source_config_ids: dict[str, str] = {}
        for source, keywords in (
            ("linkedin", "LinkedIn junior engineer"),
            ("indeed", "Indeed graduate developer"),
            ("jobs_ch", "jobs.ch Praktikum IT"),
        ):
            response = client.post(
                "/job-search/source-configs",
                headers=headers,
                json={
                    "name": f"Entry IT · {source}",
                    "configId": profile["id"],
                    "source": source,
                    "filters": {"keywords": keywords, "resultsLimit": 25},
                },
            )
            assert response.status_code == 201
            payload = response.json()
            source_config_ids[source] = payload["id"]
            assert payload["filters"]["keywords"] == keywords

        direct_company_config = client.post(
            "/job-search/source-configs",
            headers=headers,
            json={
                "name": "SBB query",
                "configId": profile["id"],
                "source": "sbb",
                "filters": {},
            },
        )
        assert direct_company_config.status_code == 422

        incomplete_preset = client.post(
            "/job-search/presets",
            headers=headers,
            json={
                "name": "Missing jobs.ch",
                "configId": profile["id"],
                "sources": ["linkedin", "jobs_ch"],
                "sourceConfigIds": {
                    "linkedin": source_config_ids["linkedin"],
                },
            },
        )
        assert incomplete_preset.status_code == 422
        assert incomplete_preset.json()["detail"] == "Select a source config for jobs_ch"

        preset_response = client.post(
            "/job-search/presets",
            headers=headers,
            json={
                "name": "Entry IT · all sources",
                "configId": profile["id"],
                "sources": ["linkedin", "indeed", "jobs_ch", "sbb"],
                "sourceConfigIds": source_config_ids,
            },
        )
        assert preset_response.status_code == 201
        preset = preset_response.json()
        assert preset["sourceConfigIds"] == source_config_ids
        assert client.get("/job-search/presets", headers=other_owner).json() == []
        assert client.get("/job-search/source-configs", headers=other_owner).json() == []

        schedule_response = client.post(
            "/job-search/schedules",
            headers=headers,
            json={
                "name": "Entry IT every day",
                "presetId": preset["id"],
                "frequency": "daily",
                "weekdays": [],
                "localTime": "09:00:00",
                "timezone": "Europe/Zurich",
                "enabled": True,
            },
        )
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()
        assert schedule["presetId"] == preset["id"]
        assert schedule["configId"] == profile["id"]
        assert schedule["sources"] == ["linkedin", "indeed", "jobs_ch", "sbb"]
        assert schedule["sourceConfigIds"] == source_config_ids

        updated_preset = client.patch(
            f"/job-search/presets/{preset['id']}",
            headers=headers,
            json={
                "sources": ["linkedin", "sbb"],
                "sourceConfigIds": {
                    "linkedin": source_config_ids["linkedin"],
                },
            },
        )
        assert updated_preset.status_code == 200
        updated_schedule = client.get(
            f"/job-search/schedules/{schedule['id']}",
            headers=headers,
        ).json()
        assert updated_schedule["sources"] == ["linkedin", "sbb"]
        assert updated_schedule["sourceConfigIds"] == {
            "linkedin": source_config_ids["linkedin"],
        }

        blocked_source_delete = client.delete(
            f"/job-search/source-configs/{source_config_ids['linkedin']}",
            headers=headers,
        )
        assert blocked_source_delete.status_code == 409
        blocked_preset_delete = client.delete(
            f"/job-search/presets/{preset['id']}",
            headers=headers,
        )
        assert blocked_preset_delete.status_code == 409
    finally:
        app.dependency_overrides.clear()


def schedule_request(*, config_id: str, name: str) -> dict[str, object]:
    return {
        "name": name,
        "configId": config_id,
        "sources": ["linkedin", "indeed", "linkedin", "jobs_ch"],
        "frequency": "selected_days",
        "weekdays": [0, 2, 4],
        "localTime": "07:30:00",
        "timezone": "Europe/Zurich",
        "aiAnalysisEnabled": True,
        "enabled": True,
    }


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
