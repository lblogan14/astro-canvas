"""files table: cached blake3 per workspace file

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("mtime_ns", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("blake3", sa.String(length=64), nullable=False),
        sa.Column("hashed", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("path"),
    )


def downgrade() -> None:
    op.drop_table("files")
