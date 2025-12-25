"""Add vouchers.issued_by

Revision ID: 20251225_0008
Revises: 20251225_0007
Create Date: 2025-12-25

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251225_0008"
down_revision = "20251225_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: older vouchers may not have an issuer recorded.
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.add_column(
            sa.Column("issued_by", sa.BigInteger(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.drop_column("issued_by")
