"""Initial schema

Revision ID: 20251220_0001
Revises:
Create Date: 2025-12-20

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251220_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not insp.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("username", sa.String(), nullable=True),
            sa.Column("first_name", sa.String(), nullable=True),
            sa.Column("last_name", sa.String(), nullable=True),
            sa.Column(
                "is_admin",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column(
                "is_blacklisted",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column(
                "registered_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "last_active",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    if not insp.has_table("chats"):
        op.create_table(
            "chats",
            sa.Column("chat_id", sa.BigInteger(), primary_key=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    if not insp.has_table("blacklist"):
        op.create_table(
            "blacklist",
            sa.Column("tag", sa.String(), primary_key=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    if not insp.has_table("settings"):
        op.create_table(
            "settings",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=True),
        )

    if not insp.has_table("spotify_tracks"):
        op.create_table(
            "spotify_tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("spotify_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("artist", sa.String(), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("added_by", sa.BigInteger(), nullable=False),
            sa.Column(
                "added_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )

    # Best-effort unique constraint for sqlite
    try:
        existing_uqs = {uc.get("name") for uc in insp.get_unique_constraints("spotify_tracks")}
        if "uq_spotify_tracks_spotify_id" not in existing_uqs:
            op.create_unique_constraint(
                "uq_spotify_tracks_spotify_id", "spotify_tracks", ["spotify_id"]
            )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_constraint("uq_spotify_tracks_spotify_id", "spotify_tracks", type_="unique")
    op.drop_table("spotify_tracks")
    op.drop_table("settings")
    op.drop_table("blacklist")
    op.drop_table("chats")
    op.drop_table("users")
