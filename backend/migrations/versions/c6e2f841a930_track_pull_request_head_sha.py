"""track current pull request and check-run head SHAs

Revision ID: c6e2f841a930
Revises: 9c41a72e6f30
Create Date: 2026-10-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6e2f841a930"
down_revision: Union[str, Sequence[str], None] = "9c41a72e6f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pull_requests",
        sa.Column("head_sha", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "check_run",
        sa.Column("head_sha", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("check_run", "head_sha")
    op.drop_column("pull_requests", "head_sha")
