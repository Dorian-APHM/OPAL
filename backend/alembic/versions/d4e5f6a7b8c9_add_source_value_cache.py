"""add source_value_cache tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_value_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cdm_name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False),
        sa.Column("source_value", sa.String(1000), nullable=False),
        sa.Column("source_name", sa.String(1000), nullable=True, server_default=""),
        sa.Column("n_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_persons", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mapped_concept_id", sa.Integer(), nullable=True),
        sa.Column("mapped_concept_name", sa.String(500), nullable=True, server_default=""),
        sa.Column("mapped_vocabulary_id", sa.String(100), nullable=True, server_default=""),
        sa.Column("mapped_standard_concept", sa.String(1), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_svc_cdm_domain", "source_value_cache", ["cdm_name", "domain"])
    op.create_index("ix_svc_search", "source_value_cache", ["cdm_name", "domain", "source_value"])

    op.create_table(
        "source_value_cache_status",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cdm_name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cdm_name", "domain", name="uq_svc_status_cdm_domain"),
    )
    op.create_index("ix_svc_status_cdm", "source_value_cache_status", ["cdm_name"])


def downgrade() -> None:
    op.drop_table("source_value_cache_status")
    op.drop_table("source_value_cache")
