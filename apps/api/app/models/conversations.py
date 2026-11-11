from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ai_models import AISource
from app.core.database import Base, OwnerScoped


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationRecord(OwnerScoped, Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    context_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="profile")
    context_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    provider_session_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    messages: Mapped[list["MessageRecord"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageRecord.sequence",
    )


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="complete")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    conversation: Mapped[ConversationRecord] = relationship(back_populates="messages")


ContextKind = Literal["profile", "job", "application"]
MessageRole = Literal["user", "assistant"]
MessageSource = AISource
MessageStatus = Literal["generating", "complete", "stopped", "error"]


class MessagePayload(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    role: MessageRole
    content: str = Field(default="", max_length=200_000)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    source: MessageSource | None = None
    status: MessageStatus = "complete"

    model_config = {"populate_by_name": True}


class ConversationPayload(BaseModel):
    id: str
    title: str
    context_kind: ContextKind = Field(alias="contextKind")
    context_id: str = Field(alias="contextId")
    provider_session_id: str | None = Field(default=None, alias="providerSessionId")
    archived: bool
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    messages: list[MessagePayload]

    model_config = {"populate_by_name": True}


class ConversationUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    context_kind: ContextKind = Field(default="profile", alias="contextKind")
    context_id: str = Field(default="", max_length=160, alias="contextId")
    provider_session_id: str | None = Field(
        default=None,
        max_length=500,
        alias="providerSessionId",
    )
    archived: bool = False
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    messages: list[MessagePayload] = Field(default_factory=list, max_length=1000)

    model_config = {"populate_by_name": True}


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    context_kind: ContextKind | None = Field(default=None, alias="contextKind")
    context_id: str | None = Field(default=None, max_length=160, alias="contextId")
    archived: bool | None = None

    model_config = {"populate_by_name": True}


class MessageUpsertRequest(BaseModel):
    role: MessageRole
    content: str = Field(default="", max_length=200_000)
    created_at: datetime | None = Field(default=None, alias="createdAt")
    source: MessageSource | None = None
    status: MessageStatus = "complete"

    model_config = {"populate_by_name": True}
