"""add foreign key constraints to cohort_versions and cohort_shares

Revision ID: b1c2d3e4f5a6
Revises: 26a4acfe5afa
Create Date: 2026-03-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '26a4acfe5afa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add FK constraints on cohort_versions.cohort_id and cohort_shares.cohort_id."""
    # Remove orphan rows first (defensive — should not exist in practice)
    op.execute(
        "DELETE FROM cohort_versions WHERE cohort_id NOT IN (SELECT id FROM cohorts)"
    )
    op.execute(
        "DELETE FROM cohort_shares WHERE cohort_id NOT IN (SELECT id FROM cohorts)"
    )

    with op.batch_alter_table("cohort_versions") as batch_op:
        batch_op.create_foreign_key(
            "fk_cohort_versions_cohort_id",
            "cohorts",
            ["cohort_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("cohort_shares") as batch_op:
        batch_op.create_foreign_key(
            "fk_cohort_shares_cohort_id",
            "cohorts",
            ["cohort_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Drop FK constraints."""
    with op.batch_alter_table("cohort_shares") as batch_op:
        batch_op.drop_constraint("fk_cohort_shares_cohort_id", type_="foreignkey")

    with op.batch_alter_table("cohort_versions") as batch_op:
        batch_op.drop_constraint("fk_cohort_versions_cohort_id", type_="foreignkey")
