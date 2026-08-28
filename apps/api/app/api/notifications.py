from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.models.notifications import (
    CriticalNotificationPayload,
    CriticalNotificationRecord,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


@router.get("/critical", response_model=list[CriticalNotificationPayload])
def list_critical_notifications(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CriticalNotificationRecord]:
    try:
        return list(
            db.scalars(
                select(CriticalNotificationRecord)
                .where(CriticalNotificationRecord.severity == "critical")
                .order_by(
                    CriticalNotificationRecord.created_at.desc(),
                    CriticalNotificationRecord.id.desc(),
                )
                .limit(limit)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise database_unavailable(exc) from exc


@router.delete(
    "/critical/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_critical_notification(
    notification_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    try:
        record = db.scalar(
            select(CriticalNotificationRecord).where(
                CriticalNotificationRecord.id == notification_id
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Critical notification not found",
            )
        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise database_unavailable(exc) from exc


def database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Critical notification database is unavailable",
    )
