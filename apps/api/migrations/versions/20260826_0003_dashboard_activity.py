"""Add dashboard activity."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "20260826_0003"
down_revision = "20260825_0002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "profile_activity",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("login", sa.String(100), unique=True, nullable=False),
        sa.Column("contribution_calendar", JSONB),
        sa.Column("events", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "repository_activity",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("repository_id", sa.Uuid, sa.ForeignKey("repositories.id"), unique=True, nullable=False),
        sa.Column("weekly_commits", JSONB),
        sa.Column("punch_card", JSONB),
        sa.Column("recent_commits", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_repository_activity_repository_id", "repository_activity", ["repository_id"])
    
    op.add_column("repositories", sa.Column("stars", sa.Integer, server_default="0"))

def downgrade() -> None:
    op.drop_column("repositories", "stars")
    op.drop_index("ix_repository_activity_repository_id", table_name="repository_activity")
    op.drop_table("repository_activity")
    op.drop_table("profile_activity")
