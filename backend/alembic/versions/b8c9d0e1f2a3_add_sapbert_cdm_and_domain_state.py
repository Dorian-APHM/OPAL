"""add cdm_name to sapbert_mappings + sapbert_domain_state

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-02

In-app SapBERT mapping suggestions. Additive only:
  - sapbert_mappings gains a nullable cdm_name (legacy CSV rows stay NULL) and a
    (cdm_name, domain, source_code) lookup index.
  - new sapbert_domain_state table: per-(cdm, domain) build status + the
    persistent per-domain suggestion toggle.
Existing installs are unaffected (feature is off by default). NOTE: this app also
runs Base.metadata.create_all() at startup, which auto-creates the new table but
does NOT alter the existing sapbert_mappings — so the add_column below is the
one change a create_all-managed DB needs.
"""
import sqlalchemy as sa
from alembic import op


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sapbert_mappings", sa.Column("cdm_name", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_sapbert_lookup", "sapbert_mappings", ["cdm_name", "domain", "source_code"]
    )

    op.create_table(
        "sapbert_domain_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cdm_name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("built_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("cdm_name", "domain", name="uq_sapbert_domain_state_cdm_domain"),
    )
    op.create_index("ix_sapbert_domain_state_cdm_name", "sapbert_domain_state", ["cdm_name"])


def downgrade() -> None:
    op.drop_index("ix_sapbert_domain_state_cdm_name", table_name="sapbert_domain_state")
    op.drop_table("sapbert_domain_state")
    op.drop_index("ix_sapbert_lookup", table_name="sapbert_mappings")
    op.drop_column("sapbert_mappings", "cdm_name")
