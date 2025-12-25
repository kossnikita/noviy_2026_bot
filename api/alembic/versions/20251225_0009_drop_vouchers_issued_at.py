"""Drop vouchers.issued_at

Revision ID: 20251225_0009
Revises: 20251225_0008
Create Date: 2025-12-25

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251225_0009"
down_revision = "20251225_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # issued_at duplicates created_at for our use-case; keep created_at only.
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.drop_column("issued_at")


def downgrade() -> None:
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.add_column(sa.Column("issued_at", sa.DateTime(), nullable=True))
