"""Add photos table

Revision ID: 20251223_0006
Revises: 20251222_0005
Create Date: 2025-12-23

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251223_0006"
down_revision = "20251222_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    op.create_index("ix_photos_added_by", "photos", ["added_by"])


def downgrade() -> None:
    op.drop_index("ix_photos_added_by", table_name="photos")
    op.drop_table("photos")
