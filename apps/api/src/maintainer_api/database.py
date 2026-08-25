from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
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


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
