"""add db_type to cdm_configs

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-13

Multi-engine CDM connectors. Adds a `db_type` column to cdm_configs selecting the
database engine driving each CDM connection (postgresql / oracle / sqlserver).
Additive and backward-compatible: existing rows default to "postgresql", which is
the only engine OPAL supported historically.
"""
import sqlalchemy as sa
from alembic import op


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cdm_configs",
        sa.Column(
            "db_type",
            sa.String(length=32),
            nullable=False,
            server_default="postgresql",
        ),
    )


def downgrade() -> None:
    op.drop_column("cdm_configs", "db_type")
