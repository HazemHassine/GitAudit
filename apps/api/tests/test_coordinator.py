from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from maintainer_api.config import Settings
from maintainer_api.coordinator import RepositorySyncCoordinator
from maintainer_api.database import Base, RepositoryRecord
from maintainer_api.domain import MonitoringState, ScanStatus


class MockRepositoryService:
    def __init__(self) -> None:
        self.scanned_ids: list[str] = []
        self.should_fail = False

    async def sync_all(self, session: AsyncSession):
        repo1 = RepositoryRecord(
            id=uuid4(),
            github_id=1,
            owner="acme",
            name="repo1",
            default_branch="main",
            html_url="https://github.com/acme/repo1",
            monitoring_state=MonitoringState.ACTIVE.value,
            last_scanned_at=None,
        )
        repo2 = RepositoryRecord(
            id=uuid4(),
            github_id=2,
            owner="acme",
            name="repo2",
            default_branch="main",
            html_url="https://github.com/acme/repo2",
            monitoring_state=MonitoringState.ACTIVE.value,
            last_scanned_at=datetime.now(UTC),
            latest_scan_status=ScanStatus.COMPLETED.value,
        )
        session.add_all([repo1, repo2])
        await session.commit()
        return 2, [repo1, repo2]

    async def scan(self, session: AsyncSession, record: RepositoryRecord):
        if self.should_fail:
            raise RuntimeError("Scan error")
        self.scanned_ids.append(str(record.id))


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


async def test_coordinator_trigger_and_scan(session_factory: async_sessionmaker[AsyncSession]) -> None:
    settings = Settings(
        github_auth_mode="auto",
        github_token="fake_token",
        auto_scan_on_startup=False,
        scan_stale_after_minutes=60,
    )
    service = MockRepositoryService()
    coordinator = RepositorySyncCoordinator(settings, session_factory, service)

    # Initial status
    status = coordinator.status
    assert status.running is False
    assert status.discovered == 0

    # Trigger run
    status = coordinator.trigger(force=False)
    assert status.running is True

    # Calling trigger again while running should return current status
    status_dup = coordinator.trigger(force=False)
    assert status_dup.running is True

    # Wait for run task to complete
    if coordinator._run_task:
        await coordinator._run_task

    status_after = coordinator.status
    assert status_after.running is False
    assert status_after.discovered == 2
    assert status_after.monitored == 2
    assert status_after.queued == 1  # Only repo1 needed scan
    assert status_after.scanned == 1
    assert len(service.scanned_ids) == 1

    await coordinator.close()


async def test_coordinator_needs_scan() -> None:
    settings = Settings(scan_stale_after_minutes=30)
    coordinator = RepositorySyncCoordinator(settings, None, None)

    # Never scanned
    r1 = RepositoryRecord(id=uuid4(), github_id=1, owner="a", name="b", default_branch="main", html_url="https://github.com/a/b", last_scanned_at=None)
    assert coordinator._needs_scan(r1) is True

    # Previously failed
    r2 = RepositoryRecord(id=uuid4(), github_id=2, owner="a", name="c", default_branch="main", html_url="https://github.com/a/c", last_scanned_at=datetime.now(UTC), latest_scan_status=ScanStatus.FAILED.value)
    assert coordinator._needs_scan(r2) is True

    # Fresh scan
    r3 = RepositoryRecord(id=uuid4(), github_id=3, owner="a", name="d", default_branch="main", html_url="https://github.com/a/d", last_scanned_at=datetime.now(UTC) - timedelta(minutes=10), latest_scan_status=ScanStatus.COMPLETED.value)
    assert coordinator._needs_scan(r3) is False

    # Stale scan
    r4 = RepositoryRecord(id=uuid4(), github_id=4, owner="a", name="e", default_branch="main", html_url="https://github.com/a/e", last_scanned_at=datetime.now(UTC) - timedelta(minutes=45), latest_scan_status=ScanStatus.COMPLETED.value)
    assert coordinator._needs_scan(r4) is True

    # Timezone-naive stale scan
    r5 = RepositoryRecord(id=uuid4(), github_id=5, owner="a", name="f", default_branch="main", html_url="https://github.com/a/f", last_scanned_at=(datetime.now(UTC) - timedelta(minutes=45)).replace(tzinfo=None), latest_scan_status=ScanStatus.COMPLETED.value)
    assert coordinator._needs_scan(r5) is True


async def test_coordinator_scan_failure(session_factory: async_sessionmaker[AsyncSession]) -> None:
    settings = Settings(
        github_auth_mode="auto",
        github_token="fake_token",
        scan_stale_after_minutes=60,
    )
    service = MockRepositoryService()
    service.should_fail = True
    coordinator = RepositorySyncCoordinator(settings, session_factory, service)

    coordinator.trigger(force=True)
    if coordinator._run_task:
        await coordinator._run_task

    status = coordinator.status
    assert status.failed == 2
    assert status.scanned == 0

    await coordinator.close()


async def test_coordinator_start_and_interval(session_factory: async_sessionmaker[AsyncSession]) -> None:
    settings = Settings(
        github_auth_mode="auto",
        github_token="fake_token",
        auto_scan_on_startup=True,
        auto_scan_interval_minutes=1,
    )
    service = MockRepositoryService()
    coordinator = RepositorySyncCoordinator(settings, session_factory, service)

    coordinator.start()
    assert coordinator._run_task is not None
    assert coordinator._interval_task is not None

    await coordinator.close()
    assert coordinator._interval_task.cancelled() or coordinator._interval_task.done()
