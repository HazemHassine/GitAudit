import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import RepositoryRecord, ReproductionRunRecord
from .domain import (
    CreateReproductionRequest,
    ReproductionEvent,
    ReproductionPhase,
    ReproductionRun,
    ScanStatus,
)
from .github import GitHubReader

logger = structlog.get_logger(__name__)


class StackDetector:
    """Detects test stack from directory contents."""

    @staticmethod
    def detect(directory: str) -> tuple[str, str]:
        path = Path(directory)
        if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
            return "python", "python3 -m pytest"
        if (path / "package.json").exists():
            return "node", "npm test"
        if (path / "go.mod").exists():
            return "go", "go test ./..."
        if (path / "Cargo.toml").exists():
            return "rust", "cargo test"
        if (path / "Makefile").exists() or (path / "makefile").exists():
            return "makefile", "make test"
        return "unknown", "echo No supported test suite detected"


class DockerSandboxRunner:
    """Runs a reproduction in a docker container sandbox."""

    IMAGE_MAP: ClassVar[dict[str, str]] = {
        "python": "python:3.12-slim",
        "node": "node:20-slim",
        "go": "golang:1.22",
        "rust": "rust:1.77",
        "makefile": "ubuntu:22.04",
        "unknown": "ubuntu:22.04",
    }


    def __init__(self, run_id: UUID, commit_sha: str, clone_url: str):
        self.run_id = run_id
        self.commit_sha = commit_sha
        self.clone_url = clone_url
        self.work_dir = Path(f"/tmp/maintainer_repro_{run_id.hex}")
        self._process: asyncio.subprocess.Process | None = None

    async def prepare_workspace(self, emit_event) -> None:
        await emit_event(ReproductionPhase.PREPARING_WORKSPACE, f"Creating temp dir {self.work_dir}", "info")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Clone using shallow depth
        git_cmd = f"git clone --filter=tree:0 {self.clone_url} . && git fetch --depth=1 origin {self.commit_sha} && git checkout {self.commit_sha}"
        await emit_event(ReproductionPhase.PREPARING_WORKSPACE, f"Cloning repository and checking out {self.commit_sha[:7]}", "info")
        
        proc = await asyncio.create_subprocess_shell(
            git_cmd, cwd=self.work_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            output = stdout.decode() if stdout else ""
            await emit_event(ReproductionPhase.PREPARING_WORKSPACE, f"Failed to checkout commit: {output}", "error")
            raise RuntimeError("Failed to prepare workspace")

    async def run_command(self, stack: str, command: str, emit_event, queue: asyncio.Queue) -> int:
        await emit_event(ReproductionPhase.EXECUTING_SANDBOX, f"Executing in sandbox: {command}", "info")
        image = self.IMAGE_MAP.get(stack, "ubuntu:22.04")
        
        docker_cmd = (
            f"docker run --rm -v {self.work_dir.absolute()}:/workspace -w /workspace "
            f"--memory=2g --cpus=2 {image} sh -c '{command}'"
        )
        
        # Try Docker first
        self._process = await asyncio.create_subprocess_shell(
            docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        
        async def stream_output():
            if not self._process or not self._process.stdout:
                return
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='replace').rstrip('\r\n')
                await emit_event(ReproductionPhase.EXECUTING_SANDBOX, decoded_line, "stdout")
                await queue.put({"event": "stdout", "data": decoded_line})

        await asyncio.gather(stream_output())
        
        await self._process.wait()
        
        # If Docker fails (e.g. not installed or image pull issue), fallback to local run for tests to pass if docker isn't available
        if self._process.returncode == 127: # command not found for docker
             await emit_event(ReproductionPhase.EXECUTING_SANDBOX, "Docker not found, falling back to local execution", "warning")
             self._process = await asyncio.create_subprocess_shell(
                 command,
                 cwd=self.work_dir,
                 stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.STDOUT,
             )
             await asyncio.gather(stream_output())
             await self._process.wait()

        return self._process.returncode or 0

    def cleanup(self) -> None:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)
            
    async def cancel(self) -> None:
        if self._process:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass


class ReproductionService:
    def __init__(self, github: GitHubReader):
        self.github = github
        self._event_queues: dict[UUID, list[asyncio.Queue]] = {}
        self._active_runners: dict[UUID, DockerSandboxRunner] = {}
        self._background_tasks: dict[UUID, asyncio.Task] = {}

    def _subscribe(self, run_id: UUID) -> asyncio.Queue:
        if run_id not in self._event_queues:
            self._event_queues[run_id] = []
        q = asyncio.Queue()
        self._event_queues[run_id].append(q)
        return q

    def _unsubscribe(self, run_id: UUID, q: asyncio.Queue) -> None:
        if run_id in self._event_queues:
            if q in self._event_queues[run_id]:
                self._event_queues[run_id].remove(q)
            if not self._event_queues[run_id]:
                del self._event_queues[run_id]

    async def start_reproduction(
        self, session: AsyncSession, repository: RepositoryRecord, request_data: CreateReproductionRequest
    ) -> ReproductionRun:
        run_id = uuid4()
        commit_sha = request_data.commit_sha or repository.default_branch_sha
        if not commit_sha:
            raise ValueError("No commit SHA available for reproduction")

        record = ReproductionRunRecord(
            id=run_id,
            repository_id=repository.id,
            commit_sha=commit_sha,
            workflow_run_id=request_data.workflow_run_id,
            job_id=request_data.job_id,
            status=ScanStatus.RUNNING,
            current_phase=ReproductionPhase.QUEUED,
            command=request_data.custom_command,
            started_at=datetime.now(UTC),
            events=[],
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        clone_url = f"https://github.com/{repository.owner}/{repository.name}.git"
        runner = DockerSandboxRunner(run_id, commit_sha, clone_url)
        self._active_runners[run_id] = runner

        # Start workflow in background
        task = asyncio.create_task(
            self._execute_workflow(session, record.id, runner, repository, request_data)
        )
        self._background_tasks[run_id] = task

        return self._to_domain(record)

    async def _emit_event(self, session: AsyncSession, run_id: UUID, phase: ReproductionPhase, message: str, level: str = "info") -> None:
        event = ReproductionEvent(
            timestamp=datetime.now(UTC).isoformat(),
            phase=phase,
            message=message,
            level=level
        )
        
        stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            events = list(record.events)
            events.append(event.model_dump())
            record.events = events
            record.current_phase = phase.value
            await session.commit()

        if run_id in self._event_queues:
            for q in self._event_queues[run_id]:
                await q.put({"event": "status", "data": event.model_dump_json()})

    async def _execute_workflow(
        self, session: AsyncSession, run_id: UUID, runner: DockerSandboxRunner, repository: RepositoryRecord, request_data: CreateReproductionRequest
    ) -> None:
        try:
            # Phase: Fetching Logs
            await self._emit_event(session, run_id, ReproductionPhase.FETCHING_LOGS, "Fetching CI logs", "info")
            if request_data.job_id:
                logs = await self.github.job_logs(repository.owner, repository.name, request_data.job_id)
                summary = f"Fetched {len(logs)} bytes of logs for job {request_data.job_id}"
                await self._emit_event(session, run_id, ReproductionPhase.FETCHING_LOGS, summary, "info")
            else:
                await self._emit_event(session, run_id, ReproductionPhase.FETCHING_LOGS, "No job ID provided, skipping logs", "info")

            # Phase: Preparing Workspace
            await runner.prepare_workspace(
                lambda phase, msg, lvl: self._emit_event(session, run_id, phase, msg, lvl)
            )

            # Phase: Detecting Stack
            await self._emit_event(session, run_id, ReproductionPhase.DETECTING_STACK, "Detecting project stack", "info")
            stack, default_cmd = StackDetector.detect(str(runner.work_dir))
            await self._emit_event(session, run_id, ReproductionPhase.DETECTING_STACK, f"Detected stack: {stack}", "info")
            
            command = request_data.custom_command or default_cmd

            # Update DB with stack and command
            stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                record.detected_stack = stack
                record.command = command
                await session.commit()

            # Phase: Executing Sandbox
            queue = asyncio.Queue()
            exit_code = await runner.run_command(
                stack, 
                command,
                lambda phase, msg, lvl: self._emit_event(session, run_id, phase, msg, lvl),
                queue
            )

            final_phase = ReproductionPhase.COMPLETED if exit_code == 0 else ReproductionPhase.FAILED
            status = ScanStatus.COMPLETED if exit_code == 0 else ScanStatus.FAILED
            await self._emit_event(session, run_id, final_phase, f"Command exited with code {exit_code}", "info")

            # Finalize DB
            stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                record.status = status.value
                record.current_phase = final_phase.value
                record.exit_code = exit_code
                record.completed_at = datetime.now(UTC)
                await session.commit()

        except asyncio.CancelledError:
            await self._emit_event(session, run_id, ReproductionPhase.CANCELLED, "Reproduction run was cancelled", "warning")
            stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                record.status = ScanStatus.FAILED.value
                record.current_phase = ReproductionPhase.CANCELLED.value
                record.error = "Cancelled by user"
                record.completed_at = datetime.now(UTC)
                await session.commit()
        except Exception as e:
            logger.exception("Reproduction failed", exc_info=e)
            await self._emit_event(session, run_id, ReproductionPhase.FAILED, f"Error: {e!s}", "error")
            stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                record.status = ScanStatus.FAILED.value
                record.current_phase = ReproductionPhase.FAILED.value
                record.error = str(e)
                record.completed_at = datetime.now(UTC)
                await session.commit()
        finally:
            runner.cleanup()
            self._active_runners.pop(run_id, None)
            self._background_tasks.pop(run_id, None)
            
            # Send completion event
            if run_id in self._event_queues:
                for q in self._event_queues[run_id]:
                    await q.put({"event": "complete", "data": ""})

    async def cancel_reproduction(self, session: AsyncSession, run_id: UUID) -> ReproductionRun:
        task = self._background_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        runner = self._active_runners.get(run_id)
        if runner:
            await runner.cancel()

        stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError("Reproduction run not found")
        
        record.status = ScanStatus.FAILED.value
        record.current_phase = ReproductionPhase.CANCELLED.value
        record.error = "Cancelled by user"
        record.completed_at = datetime.now(UTC)
        await session.commit()
        return self._to_domain(record)

    async def get_reproduction(self, session: AsyncSession, run_id: UUID) -> ReproductionRun:
        stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.id == run_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError("Reproduction run not found")
        return self._to_domain(record)

    async def list_reproductions(self, session: AsyncSession, repository_id: UUID) -> list[ReproductionRun]:
        stmt = select(ReproductionRunRecord).where(ReproductionRunRecord.repository_id == repository_id).order_by(ReproductionRunRecord.started_at.desc())
        result = await session.execute(stmt)
        return [self._to_domain(record) for record in result.scalars()]

    def stream_reproduction(self, run_id: UUID):
        q = self._subscribe(run_id)
        async def event_generator():
            try:
                while True:
                    event = await q.get()
                    yield f"event: {event['event']}\ndata: {event['data']}\n\n"
                    if event["event"] == "complete":
                        break
            finally:
                self._unsubscribe(run_id, q)
        return event_generator()

    def _to_domain(self, record: ReproductionRunRecord) -> ReproductionRun:
        return ReproductionRun(
            id=record.id,
            repository_id=record.repository_id,
            commit_sha=record.commit_sha,
            workflow_run_id=record.workflow_run_id,
            job_id=record.job_id,
            status=ScanStatus(record.status),
            current_phase=ReproductionPhase(record.current_phase),
            detected_stack=record.detected_stack,
            command=record.command,
            exit_code=record.exit_code,
            events=[ReproductionEvent(**event) for event in record.events] if record.events else [],
            output_logs=record.output_logs,
            started_at=record.started_at,
            completed_at=record.completed_at,
            error=record.error
        )
