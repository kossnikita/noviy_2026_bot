"""Add voucher_messages table for tracking sent voucher DM messages

Revision ID: 20251231_0011
Revises: 20251228_0010
Create Date: 2025-12-31

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251231_0011"
down_revision = "20251228_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clean up old prefixed state records from settings table
    op.execute("DELETE FROM settings WHERE key LIKE 'voucher_dm_%'")

    op.create_table(
        "voucher_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("voucher_code", sa.String(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )

    # Composite index for fast lookup by user and code
    op.create_index(
        "ix_voucher_messages_user_code",
        "voucher_messages",
        ["user_id", "voucher_code"],
    )
    # Index for cleanup queries (deleted_at IS NULL)
    op.create_index(
        "ix_voucher_messages_deleted_at",
        "voucher_messages",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voucher_messages_deleted_at", table_name="voucher_messages"
    )
    op.drop_index(
        "ix_voucher_messages_user_code", table_name="voucher_messages"
    )
    op.drop_table("voucher_messages")
