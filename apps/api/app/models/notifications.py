from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


class CriticalNotificationRecord(OwnerScoped, Base):
    __tablename__ = "critical_notifications"
    __table_args__ = (
        CheckConstraint(
            "severity = 'critical'",
            name="ck_critical_notifications_severity",
        ),
        CheckConstraint(
            "attempts > 0",
            name="ck_critical_notifications_attempts",
        ),
        UniqueConstraint(
            "owner_id",
            "run_id",
            "source",
            name="uq_critical_notifications_owner_run_source",
        ),
        Index(
            "ix_critical_notifications_owner_created_at",
            "owner_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="critical",
        server_default=text("'critical'"),
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )


class CriticalNotificationPayload(BaseModel):
    id: str
    severity: Literal["critical"]
    category: Literal["parser_failure", "parser_partial"]
    source: str
    title: str
    description: str
    attempts: int = Field(ge=1)
    run_id: str = Field(alias="runId")
    created_at: datetime = Field(alias="createdAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
