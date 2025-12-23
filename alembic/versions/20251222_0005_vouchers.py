"""Add vouchers table

Revision ID: 20251222_0005
Revises: 20251222_0004
Create Date: 2025-12-22

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251222_0005"
down_revision = "20251222_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vouchers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )

    op.create_index("ix_vouchers_user_id", "vouchers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_vouchers_user_id", table_name="vouchers")
    op.drop_table("vouchers")
