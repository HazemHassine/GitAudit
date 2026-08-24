import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .database import RepositoryRecord
from .domain import ScanStatus, SyncStatus
from .service import RepositoryService

logger = structlog.get_logger(__name__)


class RepositorySyncCoordinator:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        service: RepositoryService,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._service = service
        self._state = SyncStatus()
        self._run_task: asyncio.Task[None] | None = None
        self._interval_task: asyncio.Task[None] | None = None

    @property
    def status(self) -> SyncStatus:
        return self._state.model_copy(deep=True)

    def start(self) -> None:
        if self._settings.auto_scan_on_startup and self._settings.github_configured:
            self.trigger()
        if self._settings.auto_scan_interval_minutes > 0 and self._settings.github_configured:
            self._interval_task = asyncio.create_task(self._interval_loop())

    def trigger(self, *, force: bool = False) -> SyncStatus:
        if self._run_task and not self._run_task.done():
            return self.status
        self._state = SyncStatus(running=True, started_at=datetime.now(UTC))
        self._run_task = asyncio.create_task(self._run(force=force))
        return self.status

    async def close(self) -> None:
        tasks = [task for task in (self._run_task, self._interval_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _interval_loop(self) -> None:
        interval = self._settings.auto_scan_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            self.trigger()

    async def _run(self, *, force: bool) -> None:
        self._state = SyncStatus(running=True, started_at=datetime.now(UTC))
        try:
            async with self._session_factory() as session:
                discovered, repositories = await self._service.sync_all(session)
            candidates = [record for record in repositories if force or self._needs_scan(record)]
            self._state.discovered = discovered
            self._state.monitored = len(repositories)
            self._state.queued = len(candidates)
            semaphore = asyncio.Semaphore(self._settings.max_concurrent_scans)
            await asyncio.gather(
                *(self._scan_repository(record.id, semaphore) for record in candidates)
            )
        except Exception as exc:
            self._state.error = str(exc)
            logger.exception("repository_sync_failed", error=str(exc))
        finally:
            self._state.running = False
            self._state.completed_at = datetime.now(UTC)

    def _needs_scan(self, record: RepositoryRecord) -> bool:
        if record.latest_scan_status == ScanStatus.FAILED.value:
            return True
        if record.last_scanned_at is None:
            return True
        last_scanned = record.last_scanned_at
        if last_scanned.tzinfo is None:
            last_scanned = last_scanned.replace(tzinfo=UTC)
        stale_before = datetime.now(UTC) - timedelta(
            minutes=self._settings.scan_stale_after_minutes
        )
        return last_scanned < stale_before

    async def _scan_repository(self, repository_id: UUID, semaphore: asyncio.Semaphore) -> None:
        async with semaphore, self._session_factory() as session:
            record = await session.get(RepositoryRecord, repository_id)
            if record is None:
                return
            try:
                await self._service.scan(session, record)
                self._state.scanned += 1
            except Exception as exc:  # noqa: BLE001 - one repository must not stop the batch
                self._state.failed += 1
                logger.warning(
                    "automatic_repository_scan_failed",
                    repository_id=str(repository_id),
                    repository=f"{record.owner}/{record.name}",
                    error=str(exc),
                )
