from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from sqlalchemy.orm import relationship

from typing import TYPE_CHECKING

from app.commit.models import Commit


if TYPE_CHECKING:
    from app.check.models import CheckRun

if TYPE_CHECKING:
    from app.review.models import Review

if TYPE_CHECKING:
    from app.repository.models import Repository

if TYPE_CHECKING:
    from app.outcome.models import PullRequestOutcome


if TYPE_CHECKING:
    from app.commit.models import Commit

if TYPE_CHECKING:
    from app.risk.models import RiskAssessment

class PullRequest(BaseModel):
    __tablename__ = "pull_requests"

    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "github_id",
            name="uq_pull_request_repository_github",
        ),
        Index("ix_pull_request_repository_id", "repository_id"),
        Index("ix_pull_request_github_id", "github_id"),
        Index("ix_pull_request_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True) 

    github_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    repository_id: Mapped[int] = mapped_column(
        ForeignKey(
            "repository.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    number: Mapped[int] = mapped_column(
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    author: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="unknown"
    )

    base_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="main"
    )

    head_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="unknown"
    )

    head_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )


    is_draft: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    repository: Mapped["Repository"] = relationship(
        back_populates="pull_requests",
    )

    commits: Mapped[list["Commit"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    changed_files = relationship(
        "ChangedFile",
        back_populates="pull_request",
        cascade="all, delete-orphan"
    )

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    check_runs: Mapped[list["CheckRun"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="pull_request",
        cascade="all, delete-orphan",
    )

    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
    )

    merged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    outcome: Mapped["PullRequestOutcome | None"] = relationship(
        back_populates="pull_request",
        uselist=False,
        cascade="all, delete-orphan",
    )

    merged_at: Mapped[datetime | None] = mapped_column()

    closed_at: Mapped[datetime | None] = mapped_column()