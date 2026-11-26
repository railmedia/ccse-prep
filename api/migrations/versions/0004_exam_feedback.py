"""Exam feedback mode.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "exam_sessions",
        sa.Column("feedback", sa.Text(), server_default="end", nullable=False),
    )
    op.create_check_constraint("feedback_valid", "exam_sessions", "feedback IN ('end','immediate')")


def downgrade() -> None:
    op.drop_constraint("ck_exam_sessions_feedback_valid", "exam_sessions", type_="check")
    op.drop_column("exam_sessions", "feedback")
