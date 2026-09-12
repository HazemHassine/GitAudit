"""Durable audit queue, evidence, approvals, quota and PR ownership."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260912_0005"
down_revision = "20260826_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable audit tables and seed the coordination lock."""
    op.create_table(
        "audit_control",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column(
            "selected",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("deep_review", sa.Boolean(), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column(
            "checks",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "findings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "validation",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "plan",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("plan_version", sa.String(length=64), nullable=True),
        sa.Column("approved_version", sa.String(length=64), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("session_name", sa.Text(), nullable=True),
        sa.Column("remote_state", sa.String(length=50), nullable=True),
        sa.Column(
            "patch",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("corrections", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "operation",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["audit_batches.id"],
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "repository_id"),
        sa.UniqueConstraint("session_name"),
    )
    op.create_table(
        "audit_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["audit_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["audit_batches.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["audit_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_key"),
    )
    op.create_table(
        "audit_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["audit_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "audit_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["audit_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "audit_prs",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column(
            "pending",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
        ),
        sa.PrimaryKeyConstraint("repository_id"),
        sa.UniqueConstraint("branch"),
    )
    op.create_table(
        "audit_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "checks",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_index("ix_audit_runs_batch_id", "audit_runs", ["batch_id"])
    op.create_index("ix_audit_runs_repository_id", "audit_runs", ["repository_id"])
    op.create_index("ix_audit_runs_stage", "audit_runs", ["stage"])
    op.create_index("ix_audit_jobs_available_at", "audit_jobs", ["available_at"])
    op.create_index("ix_audit_jobs_lease_until", "audit_jobs", ["lease_until"])
    op.create_index("ix_audit_events_batch_id", "audit_events", ["batch_id"])
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_audit_approvals_run_id", "audit_approvals", ["run_id"])
    op.create_index("ix_audit_reservations_created_at", "audit_reservations", ["created_at"])
    op.execute("INSERT INTO audit_control (id, paused, selected) VALUES (1, false, '[]')")


def downgrade() -> None:
    """Remove only audit-owned tables."""
    op.drop_table("audit_cache")
    op.drop_table("audit_prs")
    op.drop_table("audit_reservations")
    op.drop_table("audit_approvals")
    op.drop_table("audit_events")
    op.drop_table("audit_jobs")
    op.drop_table("audit_runs")
    op.drop_table("audit_batches")
    op.drop_table("audit_control")
