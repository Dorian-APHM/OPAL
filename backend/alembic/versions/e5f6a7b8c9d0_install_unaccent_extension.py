"""install unaccent extension for case + accent insensitive search

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-22

The unaccent extension allows search like 'Meta' to match 'Méta'.
Requires superuser privileges on first install.

NOTE: For external OMOP CDM databases, the admin must manually run
`CREATE EXTENSION IF NOT EXISTS unaccent;` on each CDM — OPAL connects
read-only and cannot install extensions there.
"""
from alembic import op


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    pass
