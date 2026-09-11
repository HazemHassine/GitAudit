from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from maintainer_api.database import Base, ReproductionRunRecord
from maintainer_api.domain import (
    ReproductionPhase,
    ScanStatus,
)
from maintainer_api.reproduction import DockerSandboxRunner, ReproductionService


class MockGitHubForReproduction:
    def __init__(self) -> None:
        self.job_logs_data = "Step 1 passed\nStep 2 failed with exit code 1"

    async def job_logs(self, owner: str, name: str, job_id: int):
        return self.job_logs_data


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


def test_docker_sandbox_runner_init_and_cleanup(tmp_path: Path) -> None:
    run_id = uuid4()
    runner = DockerSandboxRunner(run_id, "abcdef1", "https://github.com/org/repo")
    assert runner.run_id == run_id
    assert runner.commit_sha == "abcdef1"
    assert runner.clone_url == "https://github.com/org/repo"

    # Create dummy dir to test cleanup
    runner.work_dir.mkdir(parents=True, exist_ok=True)
    assert runner.work_dir.exists()
    runner.cleanup()
    assert not runner.work_dir.exists()


async def test_reproduction_service_get_and_list(session_factory: async_sessionmaker[AsyncSession]) -> None:
    service = ReproductionService(MockGitHubForReproduction())

    async with session_factory() as session:
        repo_id = uuid4()
        run_id = uuid4()

        # Not found error
        with pytest.raises(ValueError, match="Reproduction run not found"):
            await service.get_reproduction(session, run_id)

        # Insert record
        record = ReproductionRunRecord(
            id=run_id,
            repository_id=repo_id,
            commit_sha="abcdef123456",
            workflow_run_id=123,
            job_id=456,
            status=ScanStatus.RUNNING.value,
            current_phase=ReproductionPhase.QUEUED.value,
            detected_stack="python",
            command="pytest",
            events=[{"phase": "queued", "message": "Queued", "level": "info", "timestamp": "2026-08-25T10:00:00Z"}],
            started_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()

        run = await service.get_reproduction(session, run_id)
        assert run.id == run_id
        assert run.detected_stack == "python"
        assert len(run.events) == 1

        runs = await service.list_reproductions(session, repo_id)
        assert len(runs) == 1
        assert runs[0].id == run_id

        # Cancel reproduction
        cancelled = await service.cancel_reproduction(session, run_id)
        assert cancelled.status == ScanStatus.FAILED
        assert cancelled.current_phase == ReproductionPhase.CANCELLED
        assert cancelled.error == "Cancelled by user"


async def test_reproduction_service_streaming(session_factory: async_sessionmaker[AsyncSession]) -> None:
    service = ReproductionService(MockGitHubForReproduction())
    run_id = uuid4()

    generator = service.stream_reproduction(run_id)

    # Publish an event and a complete event
    q = service._event_queues[run_id][0]
    await q.put({"event": "status", "data": '{"phase": "detecting_stack", "message": "Testing"}'})
    await q.put({"event": "complete", "data": ""})

    items = []
    async for item in generator:
        items.append(item)

    assert len(items) == 2
    assert "event: status" in items[0]
    assert "event: complete" in items[1]


async def test_reproduction_service_emit_event(session_factory: async_sessionmaker[AsyncSession]) -> None:
    service = ReproductionService(MockGitHubForReproduction())
    run_id = uuid4()
    repo_id = uuid4()

    async with session_factory() as session:
        record = ReproductionRunRecord(
            id=run_id,
            repository_id=repo_id,
            commit_sha="abcdef123456",
            status=ScanStatus.RUNNING.value,
            current_phase=ReproductionPhase.QUEUED.value,
            events=[],
            started_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()

        # Subscribe queue
        queue = service._subscribe(run_id)

        await service._emit_event(session, run_id, ReproductionPhase.FETCHING_LOGS, "Fetching logs now", "info")

        # Check DB record updated
        updated = await service.get_reproduction(session, run_id)
        assert updated.current_phase == ReproductionPhase.FETCHING_LOGS
        assert len(updated.events) == 1
        assert updated.events[0].message == "Fetching logs now"

        # Check queue received event
        msg = await queue.get()
        assert msg["event"] == "status"
        assert "Fetching logs now" in msg["data"]

        service._unsubscribe(run_id, queue)
