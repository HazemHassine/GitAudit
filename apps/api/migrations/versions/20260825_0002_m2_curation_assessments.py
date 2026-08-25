"""Add Milestone 2 AI curation assessment history."""

from alembic import op


revision = "20260825_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS repository_assessments (
            id UUID PRIMARY KEY,
            repository_id UUID NOT NULL REFERENCES repositories(id),
            scan_id UUID REFERENCES repository_scans(id),
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            model VARCHAR(100) NOT NULL,
            prompt_version VARCHAR(100) NOT NULL,
            base_sha VARCHAR(64),
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            analysis JSONB,
            error TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_assessments_repository_id "
        "ON repository_assessments (repository_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_assessments_scan_id "
        "ON repository_assessments (scan_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_assessments_started_at "
        "ON repository_assessments (started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_assessments_status "
        "ON repository_assessments (status)"
    )


def downgrade() -> None:
    op.drop_table("repository_assessments")
