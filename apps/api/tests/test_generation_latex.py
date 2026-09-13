import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.documents import DocumentAttachmentRecord, DocumentFileRecord
from app.models.generation_runs import GenerationRunArtifactRecord, GenerationRunStartRequest
from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.resume import FinalResume
from app.services import generation_latex
from app.services.generation_artifact_import import import_compiled_generation_documents
from app.services.generation_latex import (
    CompiledDocument,
    build_cover_letter_tex,
    build_resume_tex,
    compile_latex_document,
    latex_escape,
)
from app.services.generation_store import create_generation_run


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode="openclaw_codex",
        openai_api_model="gpt-direct",
        openai_api_reasoning_effort="medium",
        openai_api_timeout_seconds=120,
        openai_api_max_attempts=2,
        openai_api_retry_backoff_seconds=0,
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
    )


def _start() -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="",
        idempotencyKey="latex-run",
    )


def _resume() -> FinalResume:
    return FinalResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": "master-profile",
            "targetJobId": "vacancy-1",
            "language": "English",
            "basics": {
                "fullName": "Ada Lovelace",
                "headline": "R&D_100% Engineer",
                "email": "ada@example.com",
            },
            "summary": {
                "text": "Builds APIs & platforms.",
                "evidenceIds": ["source:one"],
            },
            "evidence": [
                {"id": "source:one", "type": "source", "text": "Builds APIs & platforms."}
            ],
            "sectionOrder": ["summary"],
        }
    )


def _letter() -> CoverLetterDraft:
    return CoverLetterDraft.model_validate(
        {
            "id": "letter-1",
            "targetJobId": "vacancy-1",
            "language": "English",
            "recipient": "Example AG",
            "subject": "Platform Engineer",
            "salutation": "Dear hiring team,",
            "paragraphs": [
                {"text": "I build reliable platforms.", "evidenceIds": ["source:one"]},
                {"text": "I would welcome a conversation.", "evidenceIds": []},
            ],
            "closing": "Kind regards,",
            "signature": "Ada Lovelace",
        }
    )


def test_latex_sources_escape_untrusted_values() -> None:
    assert latex_escape("A&B_100% #{x} \\") == (r"A\&B\_100\% \#\{x\} \textbackslash{}")
    resume_tex = build_resume_tex(_resume())
    letter_tex = build_cover_letter_tex(_letter())

    assert "APIs & platforms" not in resume_tex
    assert r"APIs \& platforms" in resume_tex
    assert r"\documentclass[]{cover}" in letter_tex
    assert "\\write18" not in resume_tex + letter_tex


def test_compiler_uses_no_shell_escape_and_copies_versioned_cover_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def runner(command, *, cwd, **_kwargs):
        commands.append(command)
        workdir = Path(cwd)
        assert (workdir / "cover.cls").is_file()
        assert (workdir / "OpenFonts" / "fonts" / "lato" / "Lato-Lig.ttf").is_file()
        (workdir / "document.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        return subprocess.CompletedProcess(command, 0, stdout="compiled", stderr="")

    monkeypatch.setattr(generation_latex.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = compile_latex_document(
        document_type="cover_letter",
        engine="xelatex",
        file_name="letter.pdf",
        tex_source=build_cover_letter_tex(_letter()),
        runner=runner,
        include_cover_assets=True,
    )

    assert result.pdf.startswith(b"%PDF-")
    assert len(commands) == 2
    assert "-no-shell-escape" in commands[0]


def test_compiled_pdf_is_imported_once_and_attached_to_application(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    bundle = DraftBundle(resume=_resume())
    compiled = (
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source=build_resume_tex(_resume()),
            pdf=b"%PDF-1.7\ncompiled",
            compile_log="ok",
        ),
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        first = import_compiled_generation_documents(db, run=run, bundle=bundle, compiled=compiled)
        db.commit()
        second = import_compiled_generation_documents(db, run=run, bundle=bundle, compiled=compiled)
        db.commit()

        assert first[0].id == second[0].id
        assert db.scalar(select(func.count()).select_from(GenerationRunArtifactRecord)) == 2
        attachment = db.scalar(select(DocumentAttachmentRecord))
        file = db.scalar(select(DocumentFileRecord))
        assert attachment is not None and attachment.application_id == "application-1"
        assert file is not None and file.content_type == "application/pdf"
        assert file.content == compiled[0].pdf
