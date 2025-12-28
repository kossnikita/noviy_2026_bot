"""Add total_games to vouchers

Revision ID: 20251228_0010
Revises: 20251225_0009
Create Date: 2025-12-28

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251228_0010"
down_revision = "20251225_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add total_games column to track initial number of games on voucher
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.add_column(
            sa.Column("total_games", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.drop_column("total_games")
