from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.pull_request.models import PullRequest


class PullRequestOutcome(BaseModel):
    __tablename__ = "pull_request_outcome"

    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey(
            "pull_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )
    lifecycle_status = Column(
        String,
        nullable=False,
        default="pending",
    )

    outcome = Column(
        String,
        nullable=False,
        default="uncertain",
    )
    
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )

    merged_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    observed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="outcome",
    )