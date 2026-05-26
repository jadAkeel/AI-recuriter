"""Add skill feedback.

Revision ID: 0003_skill_feedback
Revises: 0002_embedding_metadata
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_skill_feedback"
down_revision = "0002_embedding_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("skill_name", sa.String(length=120), nullable=False),
        sa.Column("was_matched", sa.Boolean(), nullable=False),
        sa.Column("recruiter_action", sa.String(length=20), nullable=False),
        sa.Column("correct_match", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_feedback_job_id", "skill_feedback", ["job_id"])
    op.create_index("ix_skill_feedback_candidate_id", "skill_feedback", ["candidate_id"])
    op.create_index("ix_skill_feedback_skill_name", "skill_feedback", ["skill_name"])


def downgrade() -> None:
    op.drop_index("ix_skill_feedback_skill_name", table_name="skill_feedback")
    op.drop_index("ix_skill_feedback_candidate_id", table_name="skill_feedback")
    op.drop_index("ix_skill_feedback_job_id", table_name="skill_feedback")
    op.drop_table("skill_feedback")
