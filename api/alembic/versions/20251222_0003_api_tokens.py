"""Add API tokens table

Revision ID: 20251222_0003
Revises: 20251221_0002
Create Date: 2025-12-22

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251222_0003"
down_revision = "20251221_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("api_tokens")
