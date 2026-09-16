"""Backfill canonical profiles without modifying legacy resume history.

Revision ID: 20260916_0060
Revises: 20260913_0059
"""
from alembic import op
from sqlalchemy import select, union
from sqlalchemy.orm import Session

revision = '20260916_0060'
down_revision = '20260913_0059'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models.profile import ProfileRecord
    from app.models.resume import ResumeMasterRecord
    from app.services.profile_migration import ensure_candidate_profile

    with Session(bind=op.get_bind()) as db:
        owners = db.scalars(union(select(ProfileRecord.owner_id), select(ResumeMasterRecord.owner_id))).all()
        for owner in owners:
            ensure_candidate_profile(db, owner_id=owner)
        db.commit()


def downgrade() -> None:
    # Candidate data and historical versions must survive a software rollback.
    pass
