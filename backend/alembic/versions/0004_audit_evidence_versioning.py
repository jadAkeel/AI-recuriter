"""Add audit, skill evidence, and scoring versioning.

Revision ID: 0004_audit_evidence_versioning
Revises: 0003_skill_feedback
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_audit_evidence_versioning"
down_revision = "0003_skill_feedback"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
    return column_name in columns


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)} if _has_table(table_name) else set()
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    _add_column_if_missing("candidates", sa.Column("uncatalogued_skills", sa.JSON(), nullable=True))
    _add_column_if_missing("embeddings", sa.Column("embedding_language", sa.String(length=50), nullable=True))
    _add_column_if_missing("embeddings", sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("knowledge_documents", sa.Column("embedding_multilingual", sa.JSON(), nullable=True))

    _add_column_if_missing("match_results", sa.Column("scoring_version", sa.String(length=50), nullable=True))
    _add_column_if_missing("match_results", sa.Column("provider_metadata", sa.JSON(), nullable=True))
    _add_column_if_missing("match_results", sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
    _create_index_if_missing("ix_match_results_scoring_version", "match_results", ["scoring_version"])

    _add_column_if_missing("reports", sa.Column("scoring_version", sa.String(length=50), nullable=True))
    _add_column_if_missing("reports", sa.Column("provider_metadata", sa.JSON(), nullable=True))
    _add_column_if_missing("reports", sa.Column("report_version", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing("reports", sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
    _create_index_if_missing("ix_reports_scoring_version", "reports", ["scoring_version"])

    if not _has_table("skill_evidence"):
        op.create_table(
            "skill_evidence",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("candidate_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=True),
            sa.Column("skill_name", sa.String(length=120), nullable=False),
            sa.Column("normalized_skill", sa.String(length=120), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("evidence_snippet", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="has_experience"),
            sa.Column("extraction_method", sa.String(length=50), nullable=True),
            sa.Column("provider", sa.String(length=50), nullable=True),
            sa.Column("model_name", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_skill_evidence_candidate_id", "skill_evidence", ["candidate_id"])
    _create_index_if_missing("ix_skill_evidence_job_id", "skill_evidence", ["job_id"])
    _create_index_if_missing("ix_skill_evidence_skill_name", "skill_evidence", ["skill_name"])
    _create_index_if_missing("ix_skill_evidence_normalized_skill", "skill_evidence", ["normalized_skill"])
    _create_index_if_missing("ix_skill_evidence_source_type", "skill_evidence", ["source_type"])

    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    _create_index_if_missing("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    _create_index_if_missing("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    _create_index_if_missing("ix_audit_logs_action", "audit_logs", ["action"])

    if not _has_table("report_versions"):
        op.create_table(
            "report_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("report_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("candidate_id", sa.String(length=36), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("scoring_version", sa.String(length=50), nullable=True),
            sa.Column("provider_metadata", sa.JSON(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("report_id", "version", name="uq_report_versions_report_version"),
        )
    _create_index_if_missing("ix_report_versions_report_id", "report_versions", ["report_id"])
    _create_index_if_missing("ix_report_versions_job_id", "report_versions", ["job_id"])
    _create_index_if_missing("ix_report_versions_candidate_id", "report_versions", ["candidate_id"])
    _create_index_if_missing("ix_report_versions_scoring_version", "report_versions", ["scoring_version"])
    _create_index_if_missing("ix_report_versions_created_by_user_id", "report_versions", ["created_by_user_id"])


def downgrade() -> None:
    if _has_table("report_versions"):
        op.drop_table("report_versions")
    if _has_table("audit_logs"):
        op.drop_table("audit_logs")
    if _has_table("skill_evidence"):
        op.drop_table("skill_evidence")

    for table_name, columns in {
        "reports": ["is_stale", "report_version", "provider_metadata", "scoring_version"],
        "match_results": ["is_stale", "provider_metadata", "scoring_version"],
        "knowledge_documents": ["embedding_multilingual"],
        "embeddings": ["is_fallback", "embedding_language"],
        "candidates": ["uncatalogued_skills"],
    }.items():
        for column_name in columns:
            if _has_column(table_name, column_name):
                op.drop_column(table_name, column_name)
