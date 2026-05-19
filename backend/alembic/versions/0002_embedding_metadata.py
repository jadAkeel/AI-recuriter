"""Add embedding metadata.

Revision ID: 0002_embedding_metadata
Revises: 0001_initial_schema
Create Date: 2026-05-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_embedding_metadata"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Applies this database migration.
    """
    op.add_column("embeddings", sa.Column("provider", sa.String(length=50), nullable=True))
    op.add_column("embeddings", sa.Column("model_name", sa.String(length=255), nullable=True))
    op.add_column("embeddings", sa.Column("source_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """
    Reverts this database migration.
    """
    op.drop_column("embeddings", "source_hash")
    op.drop_column("embeddings", "model_name")
    op.drop_column("embeddings", "provider")
