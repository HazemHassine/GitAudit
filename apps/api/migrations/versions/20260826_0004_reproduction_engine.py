"""Add reproduction engine."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "20260826_0004"
down_revision = "20260826_0003"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "reproduction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("workflow_run_id", sa.BigInteger(), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_phase", sa.String(length=32), nullable=False),
        sa.Column("detected_stack", sa.String(length=64), nullable=True),
        sa.Column("command", sa.String(length=255), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("events", JSONB, nullable=True),
        sa.Column("output_logs", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reproduction_runs_repository_id", "reproduction_runs", ["repository_id"])
    op.create_index("ix_reproduction_runs_status", "reproduction_runs", ["status"])
    op.create_index("ix_reproduction_runs_started_at", "reproduction_runs", ["started_at"])

def downgrade() -> None:
    op.drop_index("ix_reproduction_runs_started_at", table_name="reproduction_runs")
    op.drop_index("ix_reproduction_runs_status", table_name="reproduction_runs")
    op.drop_index("ix_reproduction_runs_repository_id", table_name="reproduction_runs")
    op.drop_table("reproduction_runs")
