from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.pull_request.models import PullRequest


class Review(BaseModel):
    __tablename__ = "review"

    __table_args__ = (
        UniqueConstraint(
            "github_id",
            name="uq_review_github_id",
        ),
        Index(
            "ix_review_pull_request_id",
            "pull_request_id",
        ),
        Index(
            "ix_review_state",
            "state",
        ),
    )

    github_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey(
            "pull_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    reviewer_login: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    body: Mapped[str | None] = mapped_column(
        Text,
    )

    submitted_at: Mapped[datetime | None] = mapped_column()

    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="reviews",
    )