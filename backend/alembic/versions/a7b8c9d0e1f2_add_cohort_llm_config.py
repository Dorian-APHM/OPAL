"""add cohort_llm_config (on-premise LLM connection, singleton)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-29

Stores the instance-wide cohort-LLM endpoint used in 'on-premise' mode
(OpenAI-compatible base_url + model + Fernet-encrypted API key). Additive table;
existing installs are unaffected (feature is off by default).
"""
import sqlalchemy as sa
from alembic import op


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cohort_llm_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cohort_llm_config")
