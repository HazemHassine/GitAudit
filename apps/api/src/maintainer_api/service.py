import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import RepositoryRecord, RepositoryScanRecord
from .domain import (
    DiscoveredRepository,
    EvidenceRef,
    GitHubAccount,
    HealthDimension,
    HealthReport,
    HealthSignal,
    MonitoringState,
    RepositorySummary,
    ScanSnapshot,
    ScanStatus,
    SignalStatus,
)
from .github import GitHubEmptyRepositoryError, GitHubError, GitHubReader
from .observability import SCAN_DURATION, SCAN_TOTAL
from .scoring import score_signals

SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}


class ScanInProgressError(RuntimeError):
    pass


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _owner(metadata: dict[str, object]) -> str:
    owner = metadata.get("owner")
    return _text(owner.get("login")) if isinstance(owner, dict) else ""


def repository_summary(
    record: RepositoryRecord, stale_after_minutes: int = 360
) -> RepositorySummary:
    health = HealthReport.model_validate(record.latest_health) if record.latest_health else None
    latest_status = ScanStatus(record.latest_scan_status) if record.latest_scan_status else None
    last_scanned = record.last_scanned_at
    if last_scanned and last_scanned.tzinfo is None:
        last_scanned = last_scanned.replace(tzinfo=UTC)
    evidence_stale = bool(
        last_scanned
        and last_scanned
        < datetime.now(UTC) - timedelta(minutes=stale_after_minutes)
    )
    return RepositorySummary(
        id=record.id,
        owner=record.owner,
        name=record.name,
        description=record.description,
        default_branch=record.default_branch,
        primary_language=record.primary_language,
        private=record.private,
        html_url=record.html_url,
        default_branch_sha=record.default_branch_sha,
        last_commit_at=record.last_commit_at,
        last_scanned_at=record.last_scanned_at,
        evidence_stale=evidence_stale,
        latest_scan_status=latest_status,
        last_scan_error=record.last_scan_error,
        monitoring_state=MonitoringState(record.monitoring_state),
        health=health,
    )


def scan_snapshot(record: RepositoryScanRecord) -> ScanSnapshot:
    return ScanSnapshot(
        id=record.id,
        repository_id=record.repository_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        base_sha=record.base_sha,
        status=ScanStatus(record.status),
        signals=record.signals or [],
        report=record.report,
        source_failures=record.source_failures or [],
        error=record.error,
    )


class RepositoryService:
    def __init__(self, github: GitHubReader, stale_after_minutes: int = 360) -> None:
        self._github = github
        self._stale_after_minutes = stale_after_minutes
        self._scan_locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def account(self) -> GitHubAccount:
        data = await self._github.authenticated_user()
        login = _text(data.get("login"))
        if not login:
            raise GitHubError("GitHub account response did not contain a login")
        return GitHubAccount(
            login=login,
            avatar_url=_text(data.get("avatar_url")) or None,
            profile_url=_text(data.get("html_url"), f"https://github.com/{login}"),
        )

    async def recover_interrupted_scans(self, session: AsyncSession) -> int:
        interrupted = (
            await session.scalars(
                select(RepositoryScanRecord).where(
                    RepositoryScanRecord.status == ScanStatus.RUNNING.value
                )
            )
        ).all()
        if not interrupted:
            return 0
        completed = datetime.now(UTC)
        for scan in interrupted:
            scan.status = ScanStatus.FAILED.value
            scan.completed_at = completed
            scan.error = "Scan was interrupted before completion"
            repository = await session.get(RepositoryRecord, scan.repository_id)
            if repository and repository.latest_scan_status == ScanStatus.RUNNING.value:
                repository.latest_scan_status = ScanStatus.FAILED.value
                repository.last_scan_error = scan.error
        await session.commit()
        return len(interrupted)

    async def discover(self, session: AsyncSession) -> list[DiscoveredRepository]:
        monitored_ids = set(
            (
                await session.scalars(
                    select(RepositoryRecord.github_id).where(
                        RepositoryRecord.monitoring_state == MonitoringState.ACTIVE.value
                    )
                )
            ).all()
        )
        return [
            item
            for data in await self._github.repositories()
            if (item := self._discovered_repository(data, monitored_ids)) is not None
        ]

    @staticmethod
    def _discovered_repository(
        data: dict[str, object], monitored_ids: set[int]
    ) -> DiscoveredRepository | None:
        github_id = data.get("id")
        owner = _owner(data)
        name = _text(data.get("name"))
        if not isinstance(github_id, int) or not owner or not name:
            return None
        return DiscoveredRepository(
            github_id=github_id,
            owner=owner,
            name=name,
            description=_text(data.get("description")) or None,
            default_branch=_text(data.get("default_branch"), "main"),
            primary_language=_text(data.get("language")) or None,
            private=bool(data.get("private", False)),
            html_url=_text(data.get("html_url")),
            monitored=github_id in monitored_ids,
        )

    async def sync_all(self, session: AsyncSession) -> tuple[int, list[RepositoryRecord]]:
        raw_repositories = await self._github.repositories()
        existing_records = {
            record.github_id: record
            for record in (await session.scalars(select(RepositoryRecord))).all()
        }
        active: list[RepositoryRecord] = []
        valid_count = 0
        for data in raw_repositories:
            discovered = self._discovered_repository(data, set())
            if discovered is None:
                continue
            valid_count += 1
            record = existing_records.get(discovered.github_id)
            if record is None:
                record = RepositoryRecord(
                    github_id=discovered.github_id,
                    owner=discovered.owner,
                    name=discovered.name,
                    description=discovered.description,
                    default_branch=discovered.default_branch,
                    primary_language=discovered.primary_language,
                    private=discovered.private,
                    html_url=discovered.html_url,
                    monitoring_state=MonitoringState.ACTIVE.value,
                )
                session.add(record)
                active.append(record)
                continue
            record.owner = discovered.owner
            record.name = discovered.name
            record.description = discovered.description
            record.default_branch = discovered.default_branch
            record.primary_language = discovered.primary_language
            record.private = discovered.private
            record.html_url = discovered.html_url
            if record.monitoring_state == MonitoringState.ACTIVE.value:
                active.append(record)
        await session.commit()
        for record in active:
            if record.id is None:
                await session.refresh(record)
        return valid_count, active

    async def connect(self, session: AsyncSession, owner: str, name: str) -> RepositorySummary:
        data = await self._github.repository(owner, name)
        github_id = data.get("id")
        actual_owner = _owner(data)
        actual_name = _text(data.get("name"))
        if not isinstance(github_id, int) or not actual_owner or not actual_name:
            raise GitHubError("GitHub repository response was incomplete")
        record = await session.scalar(
            select(RepositoryRecord).where(RepositoryRecord.github_id == github_id)
        )
        if record is None:
            record = RepositoryRecord(
                github_id=github_id,
                owner=actual_owner,
                name=actual_name,
                description=_text(data.get("description")) or None,
                default_branch=_text(data.get("default_branch"), "main"),
                primary_language=_text(data.get("language")) or None,
                private=bool(data.get("private", False)),
                html_url=_text(data.get("html_url")),
                monitoring_state=MonitoringState.ACTIVE.value,
            )
            session.add(record)
        else:
            record.owner = actual_owner
            record.name = actual_name
            record.description = _text(data.get("description")) or None
            record.default_branch = _text(data.get("default_branch"), "main")
            record.primary_language = _text(data.get("language")) or None
            record.private = bool(data.get("private", False))
            record.html_url = _text(data.get("html_url"))
            record.monitoring_state = MonitoringState.ACTIVE.value
        await session.commit()
        await session.refresh(record)
        return repository_summary(record, self._stale_after_minutes)

    async def exclude(self, session: AsyncSession, record: RepositoryRecord) -> None:
        record.monitoring_state = MonitoringState.EXCLUDED.value
        await session.commit()

    async def scan(self, session: AsyncSession, record: RepositoryRecord) -> ScanSnapshot:
        lock = self._scan_locks[record.id]
        if lock.locked():
            raise ScanInProgressError(f"A scan is already running for {record.owner}/{record.name}")
        async with lock:
            return await self._scan_locked(session, record)

    async def _scan_locked(self, session: AsyncSession, record: RepositoryRecord) -> ScanSnapshot:
        timer_started = monotonic()
        started = datetime.now(UTC)
        scan = RepositoryScanRecord(
            repository_id=record.id,
            started_at=started,
            status=ScanStatus.RUNNING.value,
            signals=[],
            source_failures=[],
        )
        session.add(scan)
        record.latest_scan_status = ScanStatus.RUNNING.value
        record.last_scan_error = None
        await session.commit()
        await session.refresh(scan)

        try:
            data = await self._github.repository(record.owner, record.name)
            branch = _text(data.get("default_branch"), record.default_branch)
            try:
                commit = await self._github.default_branch(record.owner, record.name, branch)
                sha = _text(commit.get("sha"))
                if not sha:
                    raise GitHubError("GitHub did not return a default-branch commit SHA")
            except GitHubEmptyRepositoryError:
                commit = {}
                sha = ""
        except Exception as exc:
            error = (
                str(exc) if isinstance(exc, GitHubError) else "Unexpected scan collection failure"
            )
            completed = datetime.now(UTC)
            scan.completed_at = completed
            scan.status = ScanStatus.FAILED.value
            scan.error = error
            record.latest_scan_status = ScanStatus.FAILED.value
            record.last_scan_error = error
            await session.commit()
            SCAN_TOTAL.labels(status=ScanStatus.FAILED.value).inc()
            SCAN_DURATION.observe(monotonic() - timer_started)
            if isinstance(exc, GitHubError):
                raise
            raise GitHubError(error) from exc

        commit_data = commit.get("commit")
        committer = commit_data.get("committer") if isinstance(commit_data, dict) else None
        committed_at = _datetime(committer.get("date")) if isinstance(committer, dict) else None
        observed_at = datetime.now(UTC)
        signals: list[HealthSignal] = []
        source_failures: list[str] = []
        if sha:
            signals.extend(
                await self._collect_ci_signals(
                    record, branch, sha, observed_at, source_failures
                )
            )
        else:
            signals.extend(self._empty_repository_ci_signals(record, observed_at))
        signals.append(await self._collect_readme(record, observed_at, source_failures))
        report = score_signals(signals)
        completed = datetime.now(UTC)
        status = ScanStatus.PARTIAL if source_failures else ScanStatus.COMPLETED
        scan.completed_at = completed
        scan.base_sha = sha or None
        scan.status = status.value
        scan.signals = [item.model_dump(mode="json") for item in signals]
        scan.report = report.model_dump(mode="json")
        scan.source_failures = source_failures
        record.description = _text(data.get("description")) or None
        record.default_branch = branch
        record.primary_language = _text(data.get("language")) or None
        record.default_branch_sha = sha or None
        record.last_commit_at = committed_at
        record.last_scanned_at = completed
        record.latest_scan_status = status.value
        record.last_scan_error = None
        record.latest_health = report.model_dump(mode="json")
        await session.commit()
        await session.refresh(scan)
        SCAN_TOTAL.labels(status=status.value).inc()
        SCAN_DURATION.observe(monotonic() - timer_started)
        return scan_snapshot(scan)

    @staticmethod
    def _empty_repository_ci_signals(
        record: RepositoryRecord, observed_at: datetime
    ) -> list[HealthSignal]:
        evidence = EvidenceRef(
            source=f"github://{record.owner}/{record.name}/commits",
            summary="The repository does not contain a commit yet",
            observed_at=observed_at,
            url=record.html_url,
        )
        return [
            HealthSignal(
                dimension=HealthDimension.CI,
                key="default_branch_ci",
                status=SignalStatus.UNKNOWN,
                summary="No default-branch commit exists to check",
                evidence=evidence,
            ),
            HealthSignal(
                dimension=HealthDimension.CI,
                key="recent_ci_reliability",
                status=SignalStatus.UNKNOWN,
                summary="No commits exist for CI history",
                evidence=evidence,
            ),
        ]

    async def _collect_ci_signals(
        self,
        record: RepositoryRecord,
        branch: str,
        sha: str,
        observed_at: datetime,
        source_failures: list[str],
    ) -> list[HealthSignal]:
        exact_runs: list[dict[str, object]] = []
        try:
            exact_runs = await self._github.check_runs(record.owner, record.name, sha)
        except GitHubError as exc:
            source_failures.append(f"Checks API: {exc}")
        if not exact_runs:
            try:
                exact_runs = await self._github.workflow_runs(
                    record.owner, record.name, branch, sha
                )
            except GitHubError as exc:
                source_failures.append(f"Exact-commit Actions API: {exc}")

        exact = self._exact_ci_signal(record, sha, exact_runs, observed_at)
        try:
            recent = await self._github.workflow_runs(record.owner, record.name, branch)
            reliability = self._reliability_signal(record, recent, observed_at)
        except GitHubError as exc:
            source_failures.append(f"Recent Actions API: {exc}")
            reliability = self._unavailable_signal(
                record,
                HealthDimension.CI,
                "recent_ci_reliability",
                "Recent CI reliability could not be read",
                observed_at,
            )
        return [exact, reliability]

    @staticmethod
    def _exact_ci_signal(
        record: RepositoryRecord,
        sha: str,
        runs: list[dict[str, object]],
        observed_at: datetime,
    ) -> HealthSignal:
        source = f"github://{record.owner}/{record.name}/commits/{sha}/checks"
        if not runs:
            return HealthSignal(
                dimension=HealthDimension.CI,
                key="default_branch_ci",
                status=SignalStatus.UNKNOWN,
                summary=f"No CI checks found for commit {sha[:7]}",
                evidence=EvidenceRef(
                    source=source,
                    summary="No check runs or workflow runs were found for the scanned commit",
                    observed_at=observed_at,
                    url=f"{record.html_url}/commit/{sha}/checks",
                ),
            )
        completed = [run for run in runs if run.get("status") == "completed"]
        failed = [
            run
            for run in completed
            if _text(run.get("conclusion"), "unknown") not in SUCCESS_CONCLUSIONS
        ]
        pending = len(runs) - len(completed)
        evidence_run = failed[0] if failed else runs[0]
        url = _text(evidence_run.get("html_url")) or f"{record.html_url}/commit/{sha}/checks"
        if failed:
            status = SignalStatus.FAIL
            summary = f"{len(failed)} of {len(runs)} checks failed for commit {sha[:7]}"
        elif pending:
            status = SignalStatus.UNKNOWN
            summary = f"{pending} of {len(runs)} checks are still pending for commit {sha[:7]}"
        else:
            status = SignalStatus.PASS
            summary = f"All {len(runs)} checks passed for commit {sha[:7]}"
        return HealthSignal(
            dimension=HealthDimension.CI,
            key="default_branch_ci",
            status=status,
            summary=summary,
            value=len(failed),
            evidence=EvidenceRef(
                source=source,
                summary=summary,
                observed_at=observed_at,
                url=url,
            ),
        )

    @staticmethod
    def _reliability_signal(
        record: RepositoryRecord,
        runs: list[dict[str, object]],
        observed_at: datetime,
    ) -> HealthSignal:
        source = f"github://{record.owner}/{record.name}/actions"
        completed = [
            run
            for run in runs
            if run.get("status") == "completed" and isinstance(run.get("conclusion"), str)
        ]
        if not completed:
            return HealthSignal(
                dimension=HealthDimension.CI,
                key="recent_ci_reliability",
                status=SignalStatus.UNKNOWN,
                summary="No completed GitHub Actions runs found on the default branch",
                evidence=EvidenceRef(
                    source=source,
                    summary="No completed workflow runs",
                    observed_at=observed_at,
                    url=f"{record.html_url}/actions",
                ),
            )
        success_count = sum(
            _text(run.get("conclusion")) in SUCCESS_CONCLUSIONS for run in completed
        )
        reliability = success_count / len(completed)
        summary = f"{success_count} of {len(completed)} recent runs succeeded"
        return HealthSignal(
            dimension=HealthDimension.CI,
            key="recent_ci_reliability",
            status=SignalStatus.PASS if reliability >= 0.8 else SignalStatus.FAIL,
            value=reliability,
            summary=summary,
            evidence=EvidenceRef(
                source=source,
                summary=f"Recent success rate: {reliability:.0%}",
                observed_at=observed_at,
                url=f"{record.html_url}/actions",
            ),
        )

    async def _collect_readme(
        self,
        record: RepositoryRecord,
        observed_at: datetime,
        source_failures: list[str],
    ) -> HealthSignal:
        try:
            exists = await self._github.readme_exists(record.owner, record.name)
        except GitHubError as exc:
            source_failures.append(f"README API: {exc}")
            return self._unavailable_signal(
                record,
                HealthDimension.DOCUMENTATION,
                "readme_present",
                "README presence could not be checked",
                observed_at,
            )
        return HealthSignal(
            dimension=HealthDimension.DOCUMENTATION,
            key="readme_present",
            status=SignalStatus.PASS if exists else SignalStatus.FAIL,
            summary="README found" if exists else "README not found",
            evidence=EvidenceRef(
                source=f"github://{record.owner}/{record.name}/readme",
                summary="README endpoint returned content"
                if exists
                else "README endpoint returned not found",
                observed_at=observed_at,
                url=f"{record.html_url}#readme" if exists else record.html_url,
            ),
        )

    @staticmethod
    def _unavailable_signal(
        record: RepositoryRecord,
        dimension: HealthDimension,
        key: str,
        summary: str,
        observed_at: datetime,
    ) -> HealthSignal:
        return HealthSignal(
            dimension=dimension,
            key=key,
            status=SignalStatus.UNAVAILABLE,
            summary=summary,
            evidence=EvidenceRef(
                source=f"github://{record.owner}/{record.name}",
                summary=summary,
                observed_at=observed_at,
                url=record.html_url,
            ),
        )
