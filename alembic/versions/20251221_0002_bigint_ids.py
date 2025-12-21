"""Use BIGINT for Telegram ids

Revision ID: 20251221_0002
Revises: 20251220_0001
Create Date: 2025-12-21

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251221_0002"
down_revision = "20251220_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "") if dialect else ""

    # SQLite can't reliably ALTER COLUMN types; existing sqlite DBs are fine because
    # SQLite INTEGER already stores up to signed 64-bit.
    if name == "sqlite":
        return

    # Postgres (and most other DBs) can widen int -> bigint safely.
    op.alter_column(
        "users",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "chats",
        "chat_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "spotify_tracks",
        "added_by",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "") if dialect else ""

    if name == "sqlite":
        return

    op.alter_column(
        "spotify_tracks",
        "added_by",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "chats",
        "chat_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
