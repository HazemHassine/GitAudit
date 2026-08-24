from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from maintainer_api.database import Base, RepositoryRecord, RepositoryScanRecord
from maintainer_api.domain import MonitoringState, RepositoryStatus, ScanStatus
from maintainer_api.github import GitHubEmptyRepositoryError, GitHubError
from maintainer_api.service import RepositoryService


class FakeGitHub:
    def __init__(self) -> None:
        self.repository_data = [
            {
                "id": 101,
                "owner": {"login": "acme"},
                "name": "widgets",
                "description": "Widget library",
                "default_branch": "main",
                "language": "Python",
                "private": False,
                "html_url": "https://github.com/acme/widgets",
            },
            {
                "id": 102,
                "owner": {"login": "acme"},
                "name": "tools",
                "description": None,
                "default_branch": "main",
                "language": "TypeScript",
                "private": True,
                "html_url": "https://github.com/acme/tools",
            },
        ]

    async def authenticated_user(self):
        return {"login": "maintainer", "html_url": "https://github.com/maintainer"}

    async def repositories(self):
        return self.repository_data

    async def repository(self, owner: str, name: str):
        return next(
            item
            for item in self.repository_data
            if item["owner"]["login"] == owner and item["name"] == name
        )

    async def default_branch(self, owner: str, name: str, branch: str):
        return {
            "sha": "abcdef1234567890",
            "commit": {"committer": {"date": "2026-08-24T12:00:00Z"}},
        }

    async def check_runs(self, owner: str, name: str, sha: str):
        return [
            {
                "status": "completed",
                "conclusion": "success",
                "html_url": f"https://github.com/{owner}/{name}/runs/1",
            },
            {
                "status": "completed",
                "conclusion": "success",
                "html_url": f"https://github.com/{owner}/{name}/runs/2",
            },
        ]

    async def workflow_runs(
        self, owner: str, name: str, branch: str, head_sha: str | None = None
    ):
        if head_sha:
            return []
        return [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
        ]

    async def readme_exists(self, owner: str, name: str):
        return True


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_sync_all_monitors_every_new_repository_and_preserves_exclusions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = RepositoryService(FakeGitHub())
    async with session_factory() as session:
        discovered, active = await service.sync_all(session)
        assert discovered == 2
        assert {record.name for record in active} == {"widgets", "tools"}

        active[0].monitoring_state = MonitoringState.EXCLUDED.value
        await session.commit()
        _, resynced = await service.sync_all(session)

        assert {record.name for record in resynced} == {active[1].name}


async def test_scan_uses_exact_commit_checks_and_persists_complete_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = RepositoryService(FakeGitHub())
    async with session_factory() as session:
        _, records = await service.sync_all(session)
        snapshot = await service.scan(session, records[0])

        assert snapshot.status == ScanStatus.COMPLETED
        assert snapshot.base_sha == "abcdef1234567890"
        assert snapshot.report is not None
        assert snapshot.report.coverage_percent == 100
        assert snapshot.report.repository_status == RepositoryStatus.HEALTHY
        exact = next(signal for signal in snapshot.signals if signal.key == "default_branch_ci")
        assert "abcdef1" in exact.summary
        assert exact.evidence.url is not None


async def test_source_failure_creates_partial_snapshot_with_unavailable_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    github = FakeGitHub()

    async def unavailable_readme(owner: str, name: str) -> bool:
        raise GitHubError("README source unavailable")

    github.readme_exists = unavailable_readme  # type: ignore[method-assign]
    service = RepositoryService(github)
    async with session_factory() as session:
        _, records = await service.sync_all(session)
        snapshot = await service.scan(session, records[0])

        assert snapshot.status == ScanStatus.PARTIAL
        assert snapshot.report is not None
        assert snapshot.report.repository_status == RepositoryStatus.ATTENTION
        assert snapshot.source_failures == ["README API: README source unavailable"]
        readme = next(signal for signal in snapshot.signals if signal.key == "readme_present")
        assert readme.status.value == "unavailable"


async def test_essential_github_failure_is_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    github = FakeGitHub()

    async def unavailable_commit(owner: str, name: str, branch: str):
        raise GitHubError("Commit source unavailable")

    github.default_branch = unavailable_commit  # type: ignore[method-assign]
    service = RepositoryService(github)
    async with session_factory() as session:
        _, records = await service.sync_all(session)
        with pytest.raises(GitHubError, match="Commit source unavailable"):
            await service.scan(session, records[0])

        persisted_scan = await session.scalar(select(RepositoryScanRecord))
        persisted_repository = await session.scalar(select(RepositoryRecord))
        assert persisted_scan is not None
        assert persisted_scan.status == ScanStatus.FAILED.value
        assert persisted_scan.error == "Commit source unavailable"
        assert persisted_repository is not None
        assert persisted_repository.latest_scan_status == ScanStatus.FAILED.value


async def test_startup_recovers_interrupted_scan_attempts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = RepositoryService(FakeGitHub())
    async with session_factory() as session:
        _, records = await service.sync_all(session)
        repository = records[0]
        repository.latest_scan_status = ScanStatus.RUNNING.value
        session.add(
            RepositoryScanRecord(
                repository_id=repository.id,
                started_at=repository.last_scanned_at or datetime.now(UTC),
                status=ScanStatus.RUNNING.value,
                signals=[],
                source_failures=[],
            )
        )
        await session.commit()

        recovered = await service.recover_interrupted_scans(session)
        scan = await session.scalar(select(RepositoryScanRecord))

        assert recovered == 1
        assert scan is not None
        assert scan.status == ScanStatus.FAILED.value
        assert scan.completed_at is not None
        assert repository.latest_scan_status == ScanStatus.FAILED.value


async def test_empty_repository_is_an_observed_unknown_not_a_failed_scan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    github = FakeGitHub()

    async def empty_repository(owner: str, name: str, branch: str):
        raise GitHubEmptyRepositoryError("Repository does not contain a commit yet")

    github.default_branch = empty_repository  # type: ignore[method-assign]
    service = RepositoryService(github)
    async with session_factory() as session:
        _, records = await service.sync_all(session)
        snapshot = await service.scan(session, records[0])

        assert snapshot.status == ScanStatus.COMPLETED
        assert snapshot.base_sha is None
        assert snapshot.report is not None
        assert snapshot.report.repository_status == RepositoryStatus.ATTENTION
        assert next(
            signal for signal in snapshot.signals if signal.key == "default_branch_ci"
        ).status.value == "unknown"
