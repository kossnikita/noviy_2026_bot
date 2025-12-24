"""Add prizes tables

Revision ID: 20251222_0004
Revises: 20251222_0003
Create Date: 2025-12-22

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251222_0004"
down_revision = "20251222_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prizes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("friendly_name", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
    )

    op.create_table(
        "prize_remaining",
        sa.Column(
            "prize_id",
            sa.Integer(),
            sa.ForeignKey("prizes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("remaining", sa.Integer(), nullable=False),
    )

    op.create_table(
        "prize_wins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "prize_id",
            sa.Integer(),
            sa.ForeignKey("prizes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "won_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.create_index("ix_prize_wins_user_id", "prize_wins", ["user_id"])
    op.create_index("ix_prize_wins_prize_id", "prize_wins", ["prize_id"])


def downgrade() -> None:
    op.drop_index("ix_prize_wins_prize_id", table_name="prize_wins")
    op.drop_index("ix_prize_wins_user_id", table_name="prize_wins")
    op.drop_table("prize_wins")
    op.drop_table("prize_remaining")
    op.drop_table("prizes")
