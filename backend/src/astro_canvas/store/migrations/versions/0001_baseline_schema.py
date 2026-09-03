"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-09-02 22:44:21.250088
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_stats",
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("avg_ms", sa.Float(), nullable=False),
        sa.Column("n_runs", sa.Integer(), nullable=False),
        sa.Column("cost_class", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("workflow_id", "node_id"),
    )
    op.create_table(
        "outputs",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("port", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=255), nullable=False),
        sa.Column("type_id", sa.String(length=255), nullable=False),
        sa.Column("blob_hash", sa.String(length=64), nullable=False),
        sa.Column("blob_manifest", sa.Text(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("last_used", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", "port"),
    )
    with op.batch_alter_table("outputs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_outputs_blob_hash"), ["blob_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_outputs_last_used"), ["last_used"], unique=False)

    op.create_table(
        "packs",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("installed", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("started", sa.DateTime(), nullable=False),
        sa.Column("finished", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("targets_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_workflow_id"), ["workflow_id"], unique=False)

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("lock_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trust",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decided", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("hash"),
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("doc_json", sa.Text(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("modified", sa.DateTime(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "node_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("node_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_node_runs_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_node_runs_run_node", ["run_id", "node_id"], unique=False)

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("doc_json", sa.Text(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workflow_versions_workflow_id"), ["workflow_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_versions_workflow_id"))

    op.drop_table("workflow_versions")
    with op.batch_alter_table("node_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_node_runs_run_node")
        batch_op.drop_index(batch_op.f("ix_node_runs_run_id"))

    op.drop_table("node_runs")
    op.drop_table("workflows")
    op.drop_table("trust")
    op.drop_table("snapshots")
    op.drop_table("settings")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_workflow_id"))

    op.drop_table("runs")
    op.drop_table("packs")
    with op.batch_alter_table("outputs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_outputs_last_used"))
        batch_op.drop_index(batch_op.f("ix_outputs_blob_hash"))

    op.drop_table("outputs")
    op.drop_table("node_stats")
