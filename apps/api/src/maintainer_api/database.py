from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import Settings

JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class RepositoryRecord(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repository_full_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255))
    primary_language: Mapped[str | None] = mapped_column(String(100))
    private: Mapped[bool] = mapped_column(default=False)
    html_url: Mapped[str] = mapped_column(Text)
    default_branch_sha: Mapped[str | None] = mapped_column(String(64))
    last_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    latest_health: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    latest_scan_status: Mapped[str | None] = mapped_column(String(32), index=True)
    last_scan_error: Mapped[str | None] = mapped_column(Text)
    monitoring_state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    stars: Mapped[int] = mapped_column(default=0)

    scans: Mapped[list["RepositoryScanRecord"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["RepositoryAssessmentRecord"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class RepositoryScanRecord(Base):
    __tablename__ = "repository_scans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    signals: Mapped[list[dict[str, object]]] = mapped_column(JSON_DOCUMENT, default=list)
    report: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    source_failures: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    error: Mapped[str | None] = mapped_column(Text)

    repository: Mapped[RepositoryRecord] = relationship(back_populates="scans")


class RepositoryAssessmentRecord(Base):
    __tablename__ = "repository_assessments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    scan_id: Mapped[UUID | None] = mapped_column(ForeignKey("repository_scans.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(100))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, default=dict)
    analysis: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    error: Mapped[str | None] = mapped_column(Text)

    repository: Mapped[RepositoryRecord] = relationship(back_populates="assessments")


class ProfileActivityRecord(Base):
    __tablename__ = "profile_activity"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(String(100), unique=True)
    contribution_calendar: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    events: Mapped[list | None] = mapped_column(JSON_DOCUMENT)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class RepositoryActivityRecord(Base):
    __tablename__ = "repository_activity"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), unique=True, index=True)
    weekly_commits: Mapped[list | None] = mapped_column(JSON_DOCUMENT)
    punch_card: Mapped[list | None] = mapped_column(JSON_DOCUMENT)
    recent_commits: Mapped[list | None] = mapped_column(JSON_DOCUMENT)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session

class ReproductionRunRecord(Base):
    __tablename__ = "reproduction_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64))
    workflow_run_id: Mapped[int | None] = mapped_column(BigInteger)
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    current_phase: Mapped[str] = mapped_column(String(32), default="queued")
    detected_stack: Mapped[str | None] = mapped_column(String(64))
    command: Mapped[str | None] = mapped_column(String(255))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    events: Mapped[list[dict[str, object]]] = mapped_column(JSON_DOCUMENT, default=list)
    output_logs: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    repository: Mapped[RepositoryRecord] = relationship()


class AuditControlRecord(Base):
    """Singleton lock for queue controls, quota and idempotent mutations."""

    __tablename__ = "audit_control"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    paused: Mapped[bool] = mapped_column(default=False)
    selected: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditBatchRecord(Base):
    """Durable owner request, deduplicated by its idempotency key."""

    __tablename__ = "audit_batches"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    deep_review: Mapped[bool] = mapped_column(default=False)
    force: Mapped[bool] = mapped_column(default=False)
    stopped: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRunRecord(Base):
    """One repository's evidence and repair state within a batch."""

    __tablename__ = "audit_runs"
    __table_args__ = (UniqueConstraint("batch_id", "repository_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("audit_batches.id"), index=True)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    base_sha: Mapped[str | None] = mapped_column(String(64))
    branch: Mapped[str | None] = mapped_column(String(255))
    checks: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    findings: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    validation: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    plan: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    plan_version: Mapped[str | None] = mapped_column(String(64))
    approved_version: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(Text)
    session_name: Mapped[str | None] = mapped_column(Text, unique=True)
    remote_state: Mapped[str | None] = mapped_column(String(50))
    patch: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    corrections: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditJobRecord(Base):
    """Lease with a fencing token; only its current owner may finish it."""

    __tablename__ = "audit_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audit_runs.id"), unique=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    token: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(default=0)
    done: Mapped[bool] = mapped_column(default=False)


class AuditEventRecord(Base):
    """Ordered SSE replay and deduplicated provider activities."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("audit_batches.id"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audit_runs.id"), index=True)
    provider_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON_DOCUMENT)


class AuditApprovalRecord(Base):
    """Immutable owner decision attached to the actual plan digest."""

    __tablename__ = "audit_approvals"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audit_runs.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(20))
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditReservationRecord(Base):
    """Uncertain creations keep their quota until positively reconciled."""

    __tablename__ = "audit_reservations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audit_runs.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="uncertain")


class AuditPRRecord(Base):
    """Repository-wide publication association and pending write journal."""

    __tablename__ = "audit_prs"
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), primary_key=True)
    branch: Mapped[str] = mapped_column(String(255), unique=True)
    number: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(Text)
    head_sha: Mapped[str | None] = mapped_column(String(64))
    pending: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)


class AuditCacheRecord(Base):
    """Deterministic results keyed by source, configuration and tools."""

    __tablename__ = "audit_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    checks: Mapped[list] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
