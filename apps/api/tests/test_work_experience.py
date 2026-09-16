import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.profile import ProfilePayload, ProfileVersionRecord
from app.services.candidate_profile import apply_form_update


def work():
    return {
        "id": "job-a", "company": "Alpha", "title": "Engineer", "description": "Original achievement\n" * 1500,
        "stack": [{"id": "tech-a", "technology": "Python", "context": "Billing workers", "source_ids": ["cv-a"]}],
        "responsibilities": [{"id": "resp-a", "responsibility": "Billing", "decisions": "Chose queue retries"}],
        "projects": [{"id": "project-a", "name": "Ledger", "team": "4 engineers", "systems": "Billing API",
                      "users": "Finance", "load": "100k invoices/day", "evidence_ids": ["source:cv-a"]}],
    }


def test_old_clients_preserve_details_and_new_clients_can_delete_independently():
    original = work()
    current = ProfilePayload(experience=json.dumps([original]))
    old_form = {key: value for key, value in original.items() if key not in ("stack", "projects", "responsibilities")}
    old_form["description"] = "Manually corrected"
    saved = apply_form_update(current, ProfilePayload(experience=json.dumps([old_form])))
    assert json.loads(saved.experience)[0]["projects"] == original["projects"]
    edit = deepcopy(original)
    edit["stack"] = [{"id": "tech-a", "technology": "Python", "context": "Updated workers"}]
    edit["projects"] = []
    result = json.loads(apply_form_update(saved, ProfilePayload(experience=json.dumps([edit]))).experience)[0]
    assert result["stack"][0]["source_ids"] == ["cv-a"]
    assert result["stack"][0]["context"] == "Updated workers"
    assert result["projects"] == []
    assert result["responsibilities"] == original["responsibilities"]
    assert result["description"] == original["description"]


def test_optional_details_stable_ids_and_validation():
    assert ProfilePayload(experience="Legacy work history").experience == "Legacy work history"
    data = json.dumps([{"id": "job-a", "projects": [{"name": "Only name"}], "stack": [{}]}])
    first = ProfilePayload(experience=data)
    assert first.experience == ProfilePayload(experience=data).experience
    assert first.experience == ProfilePayload(experience=first.experience).experience
    assert json.loads(first.experience)[0]["projects"][0]["name"] == "Only name"
    with pytest.raises(ValidationError, match="unique"):
        ProfilePayload(experience=json.dumps([{"stack": [{"id": "same"}, {"id": "same"}]}]))
    with pytest.raises(ValidationError, match="list"):
        ProfilePayload(experience='[{"projects": "invalid"}]')


def test_api_detail_crud_roundtrips_and_versions_preserve_neighbor():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def database():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = database
    try:
        client = TestClient(app)
        original = work()
        neighbor = {"id": "job-b", "company": "Beta", "title": "Engineer", "description": "Neighbor"}
        saved = client.put("/profile", json={"name": "Ada", "experience": json.dumps([original, neighbor])})
        assert saved.status_code == 200, saved.text
        data = saved.json()
        edited = deepcopy(original)
        edited["stack"].append({"id": "tech-new", "technology": "SQL", "context": "Reporting"})
        edited["projects"][0]["description"] = "Details\n" * 3000
        edited["responsibilities"] = []
        data["experience"] = json.dumps([edited, neighbor])
        response = client.put("/profile", json=data, headers={"If-Match": saved.headers["etag"]})
        assert response.status_code == 200, response.text
        reloaded = client.get("/profile")
        assert json.loads(reloaded.json()["experience"]) == [edited, neighbor]
        stale = client.put("/profile", json=saved.json(), headers={"If-Match": saved.headers["etag"]})
        assert stale.status_code == 412
        with Session(engine) as session:
            versions = session.scalars(select(ProfileVersionRecord).order_by(ProfileVersionRecord.revision)).all()
            assert len(versions) == 2
            assert json.loads(versions[0].data["experience"])[0] == original
            assert json.loads(versions[1].data["experience"])[0] == edited
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
