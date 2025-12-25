"""Add slot, remove prize_remaining

Revision ID: 20251225_0007
Revises: 20251223_0006
Create Date: 2025-12-25

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251225_0007"
down_revision = "20251223_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Slots/prizes: keep a simple CRUD dictionary table ---
    # Old schema (20251222_0004):
    # - prizes(id, name, friendly_name, weight)
    # - prize_wins(prize_id FK prizes.id)
    # - prize_remaining (unused)
    #
    # New schema:
    # - slot(id, name, title)
    # - prize_wins(prize_name FK slot.name)
    # Client sends winners with (user_id, prize_name, won_at).

    op.create_table(
        "slot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("title", sa.String(length=128), nullable=False),
    )

    # Copy existing prize dictionary.
    op.execute(
        "INSERT INTO slot (id, name, title) "
        "SELECT id, name, friendly_name FROM prizes"
    )

    # Rebuild wins to store prize_name instead of prize_id.
    op.create_table(
        "prize_wins_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "prize_name",
            sa.String(length=64),
            sa.ForeignKey("slot.name", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "won_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.execute(
        "INSERT INTO prize_wins_new (id, user_id, prize_name, won_at) "
        "SELECT w.id, w.user_id, p.name, w.won_at "
        "FROM prize_wins w JOIN prizes p ON p.id = w.prize_id"
    )

    # Drop old wins table and indexes, then swap in the new one.
    op.drop_index("ix_prize_wins_prize_id", table_name="prize_wins")
    op.drop_index("ix_prize_wins_user_id", table_name="prize_wins")
    op.drop_table("prize_wins")
    op.rename_table("prize_wins_new", "prize_wins")
    op.create_index("ix_prize_wins_user_id", "prize_wins", ["user_id"])
    op.create_index(
        "ix_prize_wins_prize_name", "prize_wins", ["prize_name"]
    )

    # Drop unused legacy tables.
    op.drop_table("prize_remaining")
    op.drop_table("prizes")

    # SQLite needs batch mode for ALTER COLUMN.
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("issued_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "use_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    # Backfill: treat already-used vouchers as "available"; keep last used timestamp.
    op.execute(
        "UPDATE vouchers SET issued_at = created_at WHERE issued_at IS NULL"
    )
    op.execute(
        "UPDATE vouchers SET use_count = CASE WHEN used_at IS NULL THEN 0 ELSE 1 END "
        "WHERE use_count IS NULL OR use_count = 0"
    )
    op.execute("UPDATE vouchers SET user_id = NULL WHERE used_at IS NOT NULL")


def downgrade() -> None:
    # Best-effort downgrade; data semantics are lossy.
    # Vouchers
    with op.batch_alter_table("vouchers") as batch_op:
        batch_op.drop_column("use_count")
        batch_op.drop_column("issued_at")
        batch_op.alter_column(
            "user_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )

    # Slots/wins
    op.drop_index("ix_prize_wins_prize_name", table_name="prize_wins")
    op.drop_index("ix_prize_wins_user_id", table_name="prize_wins")
    op.drop_table("prize_wins")
    op.drop_table("slot")
