"""Create the Milestone 1 trustworthy scan schema."""

from alembic import op


revision = "20260824_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS lets this first migration safely adopt databases created by
    # the original create_all-based scaffold.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id UUID PRIMARY KEY,
            github_id BIGINT NOT NULL UNIQUE,
            owner VARCHAR(100) NOT NULL,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            default_branch VARCHAR(255) NOT NULL,
            primary_language VARCHAR(100),
            private BOOLEAN NOT NULL DEFAULT FALSE,
            html_url TEXT NOT NULL,
            default_branch_sha VARCHAR(64),
            last_commit_at TIMESTAMPTZ,
            last_scanned_at TIMESTAMPTZ,
            latest_health JSONB,
            latest_scan_status VARCHAR(32),
            last_scan_error TEXT,
            monitoring_state VARCHAR(32) NOT NULL DEFAULT 'active',
            CONSTRAINT uq_repository_full_name UNIQUE (owner, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS repository_scans (
            id UUID PRIMARY KEY,
            repository_id UUID NOT NULL REFERENCES repositories(id),
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            base_sha VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            signals JSONB NOT NULL DEFAULT '[]'::jsonb,
            report JSONB,
            source_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
            error TEXT
        )
        """
    )
    op.execute(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS latest_scan_status VARCHAR(32)"
    )
    op.execute("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_scan_error TEXT")
    op.execute(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS monitoring_state VARCHAR(32) DEFAULT 'active'"
    )
    op.execute("UPDATE repositories SET monitoring_state = 'active' WHERE monitoring_state IS NULL")
    op.execute("ALTER TABLE repositories ALTER COLUMN monitoring_state SET NOT NULL")
    op.execute(
        "ALTER TABLE repository_scans ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'completed'"
    )
    op.execute(
        "ALTER TABLE repository_scans ADD COLUMN IF NOT EXISTS source_failures JSONB DEFAULT '[]'::jsonb"
    )
    op.execute("ALTER TABLE repository_scans ADD COLUMN IF NOT EXISTS error TEXT")
    op.execute("UPDATE repository_scans SET status = 'completed' WHERE status IS NULL")
    op.execute(
        "UPDATE repository_scans SET source_failures = '[]'::jsonb WHERE source_failures IS NULL"
    )
    op.execute("ALTER TABLE repository_scans ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE repository_scans ALTER COLUMN source_failures SET NOT NULL")
    op.execute("ALTER TABLE repository_scans ALTER COLUMN completed_at DROP NOT NULL")
    op.execute("ALTER TABLE repository_scans ALTER COLUMN base_sha DROP NOT NULL")
    op.execute("ALTER TABLE repository_scans ALTER COLUMN report DROP NOT NULL")
    op.execute(
        """
        UPDATE repositories AS r
        SET latest_scan_status = s.status
        FROM (
            SELECT DISTINCT ON (repository_id) repository_id, status
            FROM repository_scans
            ORDER BY repository_id, started_at DESC
        ) AS s
        WHERE r.id = s.repository_id AND r.latest_scan_status IS NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repositories_monitoring_state ON repositories (monitoring_state)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repositories_latest_scan_status ON repositories (latest_scan_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_repository_scans_status ON repository_scans (status)"
    )


def downgrade() -> None:
    # The baseline can adopt a pre-Alembic database, so automated destructive
    # downgrade is intentionally disabled.
    pass
