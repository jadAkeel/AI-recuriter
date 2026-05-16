"""Initial schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.core.config import settings

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _embedding_vector_column(bind) -> sa.Column:
    if bind.dialect.name == "postgresql" and Vector is not None:
        return sa.Column("embedding_vector", Vector(settings.embedding_dimension), nullable=True)
    return sa.Column("embedding_vector", sa.JSON(), nullable=True)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("skills_detailed", sa.JSON(), nullable=True),
        sa.Column("experience", sa.JSON(), nullable=False),
        sa.Column("experience_entries", sa.JSON(), nullable=True),
        sa.Column("education", sa.JSON(), nullable=False),
        sa.Column("education_entries", sa.JSON(), nullable=True),
        sa.Column("projects", sa.JSON(), nullable=False),
        sa.Column("negative_skills", sa.JSON(), nullable=True),
        sa.Column("learning_skills", sa.JSON(), nullable=True),
        sa.Column("total_years_experience", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("optional_skills", sa.JSON(), nullable=False),
        sa.Column("seniority", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        _embedding_vector_column(bind),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_embeddings_entity"),
    )
    op.create_index("ix_embeddings_entity_type", "embeddings", ["entity_type"])
    op.create_index("ix_embeddings_entity_id", "embeddings", ["entity_id"])

    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("evaluations", sa.JSON(), nullable=False),
        sa.Column("chat_history", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_sessions_job_id", "interview_sessions", ["job_id"])
    op.create_index("ix_interview_sessions_candidate_id", "interview_sessions", ["candidate_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_category", "knowledge_documents", ["category"])

    op.create_table(
        "match_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "candidate_id", name="uq_match_results_job_candidate"),
    )
    op.create_index("ix_match_results_job_id", "match_results", ["job_id"])
    op.create_index("ix_match_results_candidate_id", "match_results", ["candidate_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("skill_gap", sa.JSON(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("weaknesses", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "candidate_id", name="uq_reports_job_candidate"),
    )
    op.create_index("ix_reports_job_id", "reports", ["job_id"])
    op.create_index("ix_reports_candidate_id", "reports", ["candidate_id"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("match_results")
    op.drop_table("knowledge_documents")
    op.drop_table("interview_sessions")
    op.drop_table("embeddings")
    op.drop_table("jobs")
    op.drop_table("users")
    op.drop_table("candidates")
