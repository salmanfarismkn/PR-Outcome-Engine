from __future__ import annotations
from datetime import datetime, UTC

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class PRFeatureSnapshot(BaseModel):
    __tablename__ = "pr_feature_snapshot"

    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey(
            "pull_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    additions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    deletions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    changed_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    commit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_authors: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    unique_reviewers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    approvals: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    change_requests: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    check_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    successful_checks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    failed_checks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    pending_checks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    is_draft: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )


    age_hours: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    
    pull_request: Mapped["PullRequest"] = relationship()