import json
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_generation_workflow import (
    FakeBackend,
    _draft,
    _fit,
    _renderer,
    _review,
    _seed,
    _settings,
    _start,
    _verifier,
    _visual_review,
)
from test_work_experience import work

from app.core.database import Base
from app.models.generation_workflow import DraftBundle
from app.models.profile import ImportedExperienceEntry, ProfilePayload, ProfileRecord
from app.models.resume import MasterResume
from app.services.candidate_profile import profile_resume
from app.services.generation_grounding import GenerationGroundingError, validate_grounded_bundle
from app.services.generation_store import create_generation_run
from app.services.generation_workflow import GenerationWorkflow
from app.services.profile_migration import merge_master_into_profile
from app.services.profile_versions import update_profile_data
from app.services.resume_import import parse_experience_with_ai
from app.services.work_experience_import import source_experience_entries


def two_jobs():
    first = work()
    first.update(description="Original achievement", start_date="2020-01", end_date="2021-01")
    second = {"id": "job-b", "company": "Beta", "title": "Engineer", "start_date": "2021-02", "is_current": True,
              "description": "Other employer", "stack": [{"id": "other-tech", "technology": "Go", "context": "Search API"}],
              "projects": [{"id": "other-project", "name": "Search", "users": "Shoppers"}]}
    return [first, second]


def test_partial_ai_import_keeps_employer_details_and_stable_source_ids():
    jobs = two_jobs()
    backend = FakeBackend([{"experience": jobs}])
    parsed = parse_experience_with_ai("Alpha and Beta source CV", "unused", "test", "low", 30, backend=backend)
    sourced = source_experience_entries(parsed, "retained-cv")
    repeated = source_experience_entries(parsed, "retained-cv")
    assert sourced == repeated
    assert sourced[0].stack[0].context == "Billing workers"
    assert sourced[0].stack[0].source_ids == ["retained-cv"]
    assert sourced[1].stack[0].technology == "Go"
    assert sourced[1].responsibilities == []
    assert sourced[1].projects[0].team == ""
    assert sourced[0].stack[0].id != sourced[1].stack[0].id
    assert "another employer" in backend.requests[0].prompt
    assert "decisions" in backend.requests[0].prompt
    assert source_experience_entries([ImportedExperienceEntry(company="Legacy", title="Developer")], "cv")[0].stack == []


def test_full_import_merge_preserves_manual_details_and_is_repeatable():
    jobs = two_jobs()
    # Use valid fragment evidence, as returned by the full typed CV importer.
    imported = profile_resume(ProfilePayload(name="Ada", experience=json.dumps(jobs)), "import-master")
    raw = imported.model_dump(mode="json", by_alias=True)
    for proof in raw["evidence"]:
        proof.update(type="source", claimType=None, experienceId=None)
        old = proof["id"]
        proof["id"] = old.replace("profile:", "source:", 1)
        # Map all references while retaining fields and item identity.
    raw = json.loads(json.dumps(raw).replace('"profile:', '"source:'))
    imported = MasterResume.model_validate(raw)
    manual = deepcopy(jobs[0])
    manual["description"] = "Manual achievement"
    manual["stack"] = [{"id": "manual-tech", "technology": "SQL", "context": "Manual reporting detail"}]
    manual["projects"] = [{"id": "manual-project", "name": "Manual project"}]
    profile = ProfilePayload(name="Ada", experience=json.dumps([manual]))
    kwargs = {"source_key": "import:cv", "source_file_id": "cv", "content_sha256": "a" * 64}
    saved = merge_master_into_profile(profile, imported, **kwargs)
    entries = json.loads(saved.experience)
    assert len(entries) == 2
    assert entries[0]["id"] == manual["id"]
    assert [item["technology"] for item in entries[0]["stack"]] == ["SQL", "Python"]
    assert entries[0]["description"] == "Manual achievement\nOriginal achievement"
    assert entries[0]["stack"][1]["source_ids"] == ["cv-a", "import:cv"]
    assert entries[0]["projects"][0]["name"] == "Manual project"
    assert entries[1]["stack"][0]["technology"] == "Go"
    assert entries[1]["projects"][0]["name"] == "Search"
    assert merge_master_into_profile(saved, imported, **kwargs) == saved
    assert saved.sources[0]["download_url"] == "/profile/sources/cv"


def detailed_bundle(master):
    data = _draft()
    resume = data["resume"]
    resume["masterResumeId"] = master.id
    resume["summary"] = None
    resume["sectionOrder"] = ["experience"]
    resume["experiences"] = []
    for entry in master.experiences:
        detail = entry.stack[0]
        resume["experiences"].append({"id": f"tailored-{entry.id}", "masterExperienceId": entry.id,
            "company": entry.company, "title": entry.title,
            "period": f"{entry.start_date}–{'Present' if entry.is_current else entry.end_date}",
            "bullets": [{"id": f"bullet-{entry.id}", "text": f"{detail.technology}: {detail.context}",
                         "evidenceIds": detail.evidence_ids}]})
    used = {proof for entry in resume["experiences"] for bullet in entry["bullets"] for proof in bullet["evidenceIds"]}
    resume["evidence"] = [entry.model_dump(mode="json", by_alias=True) for entry in master.evidence if entry.id in used]
    return data


def test_generation_details_use_current_wording_and_cannot_move_between_employers():
    jobs = two_jobs()
    jobs[0]["stack"][0]["context"] = "Corrected billing architecture"
    master = profile_resume(ProfilePayload(name="Ada", experience=json.dumps(jobs)), "default")
    first = master.experiences[0]
    proofs = {item.id: item for item in master.evidence}
    assert first.projects[0].load == "100k invoices/day"
    assert first.responsibilities[0].decisions == "Chose queue retries"
    assert all(proofs[key].experience_id == first.id for key in first.stack[0].evidence_ids)
    assert all(key != "source:cv-a" for key in proofs)  # Archived wording cannot ground edits.
    data = detailed_bundle(master)
    validate_grounded_bundle(DraftBundle.model_validate(data), master_resume=master, target_job_id="vacancy-1")
    data["resume"]["experiences"][1]["bullets"][0]["evidenceIds"] = first.stack[0].evidence_ids
    with pytest.raises(GenerationGroundingError, match="another employer"):
        validate_grounded_bundle(DraftBundle.model_validate(data), master_resume=master, target_job_id="vacancy-1")


def test_every_author_reviewer_and_pdf_repair_sees_frozen_structured_details():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    _seed(sessions)
    with sessions() as db:
        profile = db.get(ProfileRecord, "default")
        data = {**profile.data, "experience": json.dumps(two_jobs())}
        update_profile_data(db, profile, data=data, reason="details")
        db.commit()
        run = create_generation_run(db, application_id="application-1", request=_start(), settings=_settings())
        frozen = run.input_snapshot["request"]["masterProfileVersion"]
        master = profile_resume(ProfilePayload.model_validate(frozen["data"]), "default")
        draft = detailed_bundle(master)
        review = {**_review(), "findings": [{"severity": "warning", "category": "clarity", "message": "Clarify the context", "document": "resume"}]}
        visual_failure = {"approved": False, "summary": "Shorten wording to fit the page", "findings": []}
        backend = FakeBackend([_fit(), draft, review, draft, visual_failure, draft, _visual_review()])
        workflow = GenerationWorkflow(settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier)
        changed = deepcopy(data)
        changed["experience"] = json.dumps([{**two_jobs()[0], "stack": [{"id": "new", "technology": "NEW AFTER START"}]}])
        update_profile_data(db, profile, data=changed, reason="edit_while_running")
        db.commit()
        workflow.evaluate_fit(db, run)
        workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
        assert len(backend.requests) == 7
        for request in backend.requests:
            context = json.loads(request.prompt.split("BEGIN UNTRUSTED APPLICATION DATA\n")[1].split("\nEND UNTRUSTED")[0])
            assert context["candidateProfileVersion"] == frozen
            jobs = context["masterResume"]["experiences"]
            assert jobs[0]["stack"][0]["context"] == "Billing workers"
            assert jobs[0]["responsibilities"][0]["decisions"] == "Chose queue retries"
            assert jobs[0]["projects"][0]["load"] == "100k invoices/day"
            assert jobs[1]["stack"][0]["technology"] == "Go"
            assert "NEW AFTER START" not in request.prompt
            assert "future contributions" in request.prompt
            assert "retain selected" in request.prompt
    engine.dispose()


def test_full_typed_ai_import_retains_detailed_source_evidence_and_unknown_fields():
    from app.models.resume import ResumeSourceExtraction, ResumeSourceFragment
    from app.services.resume_master_import import (
        MasterResumeImportError,
        import_master_resume_with_ai,
    )

    raw = profile_resume(ProfilePayload(name="Ada", experience=json.dumps(two_jobs())), "cv-master").model_dump(mode="json", by_alias=True)
    raw = json.loads(json.dumps(raw).replace('"profile:', '"source:'))
    for evidence in raw["evidence"]:
        evidence.update(type="source", claimType=None, experienceId=None)
    source = ResumeSourceExtraction(sourceFormat="docx", layout="one_column", pageCount=None, usedOcr=False,
        fragments=[ResumeSourceFragment(id=e["id"], text=e["text"], order=index, kind="paragraph", extractionMethod="docx")
                   for index, e in enumerate(raw["evidence"])])
    backend = FakeBackend([raw])
    kwargs = {"source": source, "master_resume_id": "cv-master", "backend": backend,
              "model": "test", "agent_id": "test", "thinking": "low", "timeout_seconds": 30}
    outcome = import_master_resume_with_ai(**kwargs)
    assert outcome.master_resume.experiences[0].stack[0].context == "Billing workers"
    assert outcome.master_resume.experiences[1].projects[0].team == ""
    assert "another employer" in backend.requests[0].prompt
    unsupported = deepcopy(raw)
    unsupported["experiences"][0]["projects"][0]["evidence_ids"] = []
    kwargs["backend"] = FakeBackend([unsupported])
    with pytest.raises(MasterResumeImportError, match="must cite source evidence"):
        import_master_resume_with_ai(**kwargs)
