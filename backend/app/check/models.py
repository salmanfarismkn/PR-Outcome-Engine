from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    BigInteger,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class CheckRun(BaseModel):
    __tablename__ = "check_run"

    __table_args__ = (
        UniqueConstraint(
            "github_id",
            name="uq_check_run_github_id",
        ),
        Index(
            "ix_check_run_pull_request_id",
            "pull_request_id",
        ),
        Index(
            "ix_check_run_status",
            "status",
        ),
        Index(
            "ix_check_run_conclusion",
            "conclusion",
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

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    conclusion: Mapped[str | None] = mapped_column(
        String(50),
    )

    details_url: Mapped[str | None] = mapped_column(
        Text,
    )

    started_at: Mapped[datetime | None] = mapped_column()

    completed_at: Mapped[datetime | None] = mapped_column()

    pull_request: Mapped["PullRequest"] = relationship(
        back_populates="check_runs",
    )