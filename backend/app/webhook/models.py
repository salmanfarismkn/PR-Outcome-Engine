from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class WebhookEvent(BaseModel):
    __tablename__ = "webhook_event"

    __table_args__ = (
        Index(
            "ix_webhook_event_event_type",
            "event_type",
        ),
        Index(
            "ix_webhook_event_status",
            "status",
        ),
        Index(
            "ix_webhook_event_recovery",
            "status",
            "last_attempt_at",
        ),
    )

    delivery_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="received",
    )

    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )