"""Source achievement context and measured page pressure for CV generation."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
)
from app.models.resume import MasterResume

_LIST_MARKER = re.compile(r"(?m)^[ \t]*(?:[•●▪◦‣⁃*\-]|\d+[.)])[ \t]+")


def experience_content_policy(
    db: Session,
    run: ApplicationGenerationRunRecord,
    master: MasterResume,
    *,
    max_pages: int,
) -> dict[str, Any]:
    """Keep visible source points distinct without rewriting the frozen profile.

    A profile description can contain several list items in one canonical
    bullet. Counts of canonical bullets therefore cannot measure completeness.
    Leave semantic coverage to the reviewer, with the actual source points and
    their citations available on every draft, revision and visual review.
    """
    source_achievements = [
        {
            "experienceId": experience.id,
            "company": experience.company,
            "title": experience.title,
            "achievements": [
                {
                    "sourceBulletId": bullet.id,
                    "text": point.strip(),
                    "evidenceIds": list(bullet.evidence_ids),
                }
                for bullet in experience.bullets
                for point in _LIST_MARKER.split(bullet.text)
                if point.strip()
            ],
        }
        for experience in master.experiences
    ]
    current_pages = None
    overflow = None
    if run.stage in {"pdf_checks", "final_review"}:
        db.flush()
        # Model feedback cannot authorize content reduction. Only server checks
        # bound to this run's actual CV PDF can demonstrate a page overflow.
        checks = db.scalars(
            select(GenerationRunCheckRecord)
            .join(
                GenerationRunArtifactRecord,
                GenerationRunCheckRecord.artifact_id == GenerationRunArtifactRecord.id,
            )
            .where(
                GenerationRunCheckRecord.run_id == run.id,
                GenerationRunCheckRecord.check_type == "page_count",
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.document_type == "tailored_resume",
                GenerationRunArtifactRecord.content_type == "application/pdf",
                GenerationRunCheckRecord.artifact_sha256
                == GenerationRunArtifactRecord.content_sha256,
            )
            .order_by(GenerationRunCheckRecord.created_at, GenerationRunCheckRecord.id)
        ).all()
        for check in checks:
            actual = check.data.get("actual")
            maximum = check.data.get("maximum")
            if (
                type(actual) is not int or actual < 1
                or type(maximum) is not int or maximum != max_pages
            ):
                continue
            current_pages = actual
            if check.status == "failed" and actual > max_pages:
                # Keep the measured reason after a successful repair, including
                # recovery, so a later reviewer need not undo justified cuts.
                overflow = {
                    "artifactId": check.artifact_id,
                    "actualPages": actual,
                    "maxPages": max_pages,
                }
    return {
        "sourceAchievements": source_achievements,
        "maxResumePages": max_pages,
        "currentResumePages": current_pages,
        "verifiedOverflow": overflow,
        "allowContentReduction": overflow is not None,
    }
