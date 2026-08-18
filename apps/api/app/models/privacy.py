from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, OwnerScoped


class AiPrivacySettingsRecord(OwnerScoped, Base):
    __tablename__ = "ai_privacy_settings"

    owner_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_ai_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ai_data_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiRetentionUpdateRequest(BaseModel):
    retention_days: int = Field(ge=1, le=365, alias="retentionDays")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class AiPrivacySettingsPayload(BaseModel):
    provider_name: str = Field(alias="providerName")
    current_backend: Literal["openclaw_codex", "openai_api"] = Field(
        alias="currentBackend"
    )
    retention_days: int = Field(alias="retentionDays")
    last_ai_activity_at: datetime | None = Field(default=None, alias="lastAiActivityAt")
    ai_data_expires_at: datetime | None = Field(default=None, alias="aiDataExpiresAt")

    model_config = {"populate_by_name": True}
