"""add pathways_json to cohort_versions

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cohort_versions", sa.Column("pathways_json", sa.JSON(), nullable=True))
    op.add_column("cohort_versions", sa.Column("pathways_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("cohort_versions", "pathways_at")
    op.drop_column("cohort_versions", "pathways_json")
