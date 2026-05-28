"""add schema_categories JSON to cdm_configs and analysis_settings

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-28

Allows mapping each OMOP CDM table category (clinical, vocabulary, …) to its
own PostgreSQL schema. Categories without an override fall back to omop_schema,
so existing single-schema CDMs are unaffected.
"""
import sqlalchemy as sa
from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cdm_configs", sa.Column("schema_categories", sa.JSON(), nullable=True))
    op.add_column("analysis_settings", sa.Column("schema_categories", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_settings", "schema_categories")
    op.drop_column("cdm_configs", "schema_categories")
