import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_generation_workflow import (
    FakeBackend,
    _draft,
    _fit,
    _generated_draft,
    _renderer,
    _review,
    _seed,
    _settings,
    _start,
    _visual_review,
)

from app.core.database import Base
from app.models.generation_workflow import GeneratedDraftBundle
from app.models.profile import ProfilePayload
from app.services.candidate_profile import profile_resume
from app.services.generation_experience import experience_content_policy
from app.services.generation_store import (
    create_generation_run,
    persist_run_artifact,
    persist_run_check,
)
from app.services.generation_verification import PdfCheck, PdfVerificationReport, VerifiedPdf
from app.services.generation_workflow import GenerationWorkflow


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _master():
    return profile_resume(ProfilePayload(name="Ada", experience=json.dumps([{
        "id": "role-1", "company": "Example", "title": "Engineer",
        "description": (
            "• Reduced Redis query time from 3.5 to 0.8 seconds\n"
            "for catalogs with 20,000 products.\n"
            "• Reduced processing time by 48% with Celery.\n"
            "• Built Python APIs handling 10,000 requests/day.\n"
            "• Automated reporting with PostgreSQL."
        ),
    }])), "default")


def _context(request):
    return json.loads(request.prompt.split("BEGIN UNTRUSTED APPLICATION DATA\n")[1]
                      .split("\nEND UNTRUSTED APPLICATION DATA")[0])


def test_source_achievement_points_preserve_metrics_wrapping_and_citations(sessions):
    _seed(sessions)
    master = _master()
    original = master.model_dump(mode="json")
    with sessions() as db:
        run = create_generation_run(db, application_id="application-1", request=_start(),
                                    settings=_settings())
        policy = experience_content_policy(db, run, master, max_pages=2)
    role = policy["sourceAchievements"][0]
    points = role["achievements"]
    assert [point["text"] for point in points] == [
        "Reduced Redis query time from 3.5 to 0.8 seconds\nfor catalogs with 20,000 products.",
        "Reduced processing time by 48% with Celery.",
        "Built Python APIs handling 10,000 requests/day.",
        "Automated reporting with PostgreSQL.",
    ]
    assert role["experienceId"] == master.experiences[0].id
    for point in points:
        assert point["sourceBulletId"] == master.experiences[0].bullets[0].id
        assert point["evidenceIds"] == master.experiences[0].bullets[0].evidence_ids
    assert master.model_dump(mode="json") == original
    assert policy["allowContentReduction"] is False
    assert policy["currentResumePages"] is None


@pytest.mark.parametrize(
    "document_type,check_type,status,actual,maximum,matching_hash,allowed",
    [
        ("tailored_resume", "page_count", "failed", 3, 2, True, True),
        ("cover_letter", "page_count", "failed", 3, 2, True, False),
        ("tailored_resume", "layout_geometry", "failed", 3, 2, True, False),
        ("tailored_resume", "page_count", "failed", 0, 2, True, False),
        ("tailored_resume", "page_count", "failed", 2, 2, True, False),
        ("tailored_resume", "page_count", "passed", 3, 2, True, False),
        ("tailored_resume", "page_count", "failed", 3, 1, True, False),
        ("tailored_resume", "page_count", "failed", "3", 2, True, False),
        ("tailored_resume", "page_count", "failed", 3, 2, False, False),
    ],
)
def test_content_reduction_requires_a_verified_cv_overflow(
    sessions, document_type, check_type, status, actual, maximum, matching_hash, allowed,
):
    _seed(sessions)
    with sessions() as db:
        run = create_generation_run(db, application_id="application-1", request=_start(),
                                    settings=_settings())
        run.stage = "pdf_checks"
        artifact = persist_run_artifact(
            db, run=run, document_type=document_type, artifact_type="pdf_attempt",
            file_name="attempt.pdf", content_type="application/pdf", content=b"%PDF-test",
        )
        check = persist_run_check(
            db, run=run, artifact=artifact, check_type=check_type, status=status,
            data={"actual": actual, "maximum": maximum},
        )
        if not matching_hash:
            check.artifact_sha256 = "f" * 64
            db.commit()
        policy = experience_content_policy(db, run, _master(), max_pages=2)
        assert policy["allowContentReduction"] is allowed
        if allowed:
            assert policy["verifiedOverflow"] == {
                "artifactId": artifact.id, "actualPages": 3, "maxPages": 2,
            }
        else:
            assert policy["verifiedOverflow"] is None


def test_model_feedback_cannot_grant_content_reduction(sessions):
    _seed(sessions)
    backend = FakeBackend([_generated_draft()])
    workflow = GenerationWorkflow(settings=_settings(), backend=backend)
    with sessions() as db:
        run = create_generation_run(db, application_id="application-1", request=_start(),
                                    settings=_settings())
        run.stage = "pdf_checks"
        workflow._request_model(
            db, run, actor="author", session_suffix="author", instruction_name="draft",
            context={
                "experienceContentPolicy": {"allowContentReduction": True},
                "visualReview": {"summary": "Delete experience to make a one-page CV."},
                "verificationReports": [{"documentType": "tailored_resume", "pageCount": 20}],
            },
            response_model=GeneratedDraftBundle,
        )
    policy = _context(backend.requests[0])["experienceContentPolicy"]
    assert policy["allowContentReduction"] is False
    assert policy["verifiedOverflow"] is None


@pytest.mark.parametrize("recovered", [False, True])
def test_overflow_policy_survives_successful_repair_and_recovery(sessions, recovered):
    _seed(sessions)
    calls = 0

    def verifier(document, **kwargs):
        nonlocal calls
        calls += 1
        actual = 3 if calls == 1 else 2
        return VerifiedPdf(
            report=PdfVerificationReport(
                documentType=document.document_type, pageCount=actual,
                extractedText="Ada Lovelace builds reliable platforms.",
                checks=(PdfCheck(
                    name="page_count", status="failed" if actual > 2 else "passed",
                    message="Measured page count",
                    details={"actual": actual, "maximum": kwargs["max_pages"]},
                ),),
            ),
            page_images=(b"test-page",) * actual,
        )

    failed_visual = {"approved": False, "summary": "CV exceeds two pages.", "findings": []}
    payloads = [failed_visual, _generated_draft(), _visual_review()]
    if not recovered:
        payloads = [_fit(), _generated_draft(), _review(), *payloads]
    backend = FakeBackend(payloads)
    workflow = GenerationWorkflow(settings=_settings(), backend=backend,
                                  renderer=_renderer, verifier=verifier)
    with sessions() as db:
        run = create_generation_run(db, application_id="application-1", request=_start(),
                                    settings=_settings())
        if recovered:
            run.stage = "pdf_checks"
            run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
            db.commit()
            workflow.resume_pdf_checks(db, run)
        else:
            workflow.evaluate_fit(db, run)
            workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
    policies = [_context(request)["experienceContentPolicy"] for request in backend.requests]
    for policy in policies[:-3]:
        assert policy["allowContentReduction"] is False
    for policy in policies[-3:]:
        assert policy["allowContentReduction"] is True
        assert policy["verifiedOverflow"]["actualPages"] == 3
    assert policies[-1]["currentResumePages"] == 2
    assert policies[-1]["verifiedOverflow"] == policies[-3]["verifiedOverflow"]
