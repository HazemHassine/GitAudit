from datetime import UTC, datetime

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
    RepositorySummary,
    ScanSnapshot,
    SignalStatus,
)
from .github import GitHubError, GitHubReader
from .scoring import score_signals


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


def repository_summary(record: RepositoryRecord) -> RepositorySummary:
    health = HealthReport.model_validate(record.latest_health) if record.latest_health else None
    return RepositorySummary(
        id=record.id, owner=record.owner, name=record.name, description=record.description,
        default_branch=record.default_branch, primary_language=record.primary_language,
        private=record.private, html_url=record.html_url, default_branch_sha=record.default_branch_sha,
        last_commit_at=record.last_commit_at, last_scanned_at=record.last_scanned_at, health=health,
    )


class RepositoryService:
    def __init__(self, github: GitHubReader) -> None:
        self._github = github

    async def account(self) -> GitHubAccount:
        data = await self._github.authenticated_user()
        login = _text(data.get("login"))
        if not login:
            raise GitHubError("GitHub user response did not contain a login")
        return GitHubAccount(
            login=login, avatar_url=_text(data.get("avatar_url")) or None,
            profile_url=_text(data.get("html_url"), f"https://github.com/{login}"),
        )

    async def discover(self, session: AsyncSession) -> list[DiscoveredRepository]:
        monitored_ids = set((await session.scalars(select(RepositoryRecord.github_id))).all())
        results: list[DiscoveredRepository] = []
        for data in await self._github.repositories():
            github_id = data.get("id")
            owner = _owner(data)
            name = _text(data.get("name"))
            if not isinstance(github_id, int) or not owner or not name:
                continue
            results.append(DiscoveredRepository(
                github_id=github_id, owner=owner, name=name,
                description=_text(data.get("description")) or None,
                default_branch=_text(data.get("default_branch"), "main"),
                primary_language=_text(data.get("language")) or None,
                private=bool(data.get("private", False)), html_url=_text(data.get("html_url")),
                monitored=github_id in monitored_ids,
            ))
        return results

    async def connect(self, session: AsyncSession, owner: str, name: str) -> RepositorySummary:
        data = await self._github.repository(owner, name)
        github_id = data.get("id")
        actual_owner = _owner(data)
        actual_name = _text(data.get("name"))
        if not isinstance(github_id, int) or not actual_owner or not actual_name:
            raise GitHubError("GitHub repository response was incomplete")
        existing = await session.scalar(select(RepositoryRecord).where(RepositoryRecord.github_id == github_id))
        if existing is None:
            existing = RepositoryRecord(
                github_id=github_id, owner=actual_owner, name=actual_name,
                description=_text(data.get("description")) or None,
                default_branch=_text(data.get("default_branch"), "main"),
                primary_language=_text(data.get("language")) or None,
                private=bool(data.get("private", False)), html_url=_text(data.get("html_url")),
            )
            session.add(existing)
        else:
            existing.description = _text(data.get("description")) or None
            existing.default_branch = _text(data.get("default_branch"), "main")
            existing.primary_language = _text(data.get("language")) or None
            existing.private = bool(data.get("private", False))
            existing.html_url = _text(data.get("html_url"))
        await session.commit()
        await session.refresh(existing)
        return repository_summary(existing)

    async def scan(self, session: AsyncSession, record: RepositoryRecord) -> ScanSnapshot:
        started = datetime.now(UTC)
        data = await self._github.repository(record.owner, record.name)
        branch = _text(data.get("default_branch"), record.default_branch)
        commit = await self._github.default_branch(record.owner, record.name, branch)
        sha = _text(commit.get("sha"))
        if not sha:
            raise GitHubError("GitHub did not return a default-branch commit SHA")
        commit_data = commit.get("commit")
        committer = commit_data.get("committer") if isinstance(commit_data, dict) else None
        committed_at = _datetime(committer.get("date")) if isinstance(committer, dict) else None
        observed_at = datetime.now(UTC)
        runs = await self._github.workflow_runs(record.owner, record.name, branch)
        signals = self._workflow_signals(record, runs, observed_at)
        signals.append(await self._readme_signal(record, observed_at))
        report = score_signals(signals)
        completed = datetime.now(UTC)
        scan = RepositoryScanRecord(
            repository_id=record.id, started_at=started, completed_at=completed, base_sha=sha,
            signals=[item.model_dump(mode="json") for item in signals],
            report=report.model_dump(mode="json"),
        )
        session.add(scan)
        record.description = _text(data.get("description")) or None
        record.default_branch = branch
        record.primary_language = _text(data.get("language")) or None
        record.default_branch_sha = sha
        record.last_commit_at = committed_at
        record.last_scanned_at = completed
        record.latest_health = report.model_dump(mode="json")
        await session.commit()
        await session.refresh(scan)
        return ScanSnapshot(
            id=scan.id, repository_id=record.id, started_at=started, completed_at=completed,
            base_sha=sha, signals=signals, report=report,
        )

    def _workflow_signals(
        self, record: RepositoryRecord, runs: list[dict[str, object]], observed_at: datetime
    ) -> list[HealthSignal]:
        source = f"github://{record.owner}/{record.name}/actions"
        completed = [run for run in runs if run.get("status") == "completed"]
        if not completed:
            return [HealthSignal(
                dimension=HealthDimension.CI, key="default_branch_ci", status=SignalStatus.UNKNOWN,
                summary="No completed GitHub Actions runs found on the default branch",
                evidence=EvidenceRef(source=source, summary="No completed workflow runs", observed_at=observed_at),
            )]
        latest = completed[0]
        conclusion = _text(latest.get("conclusion"), "unknown")
        url = _text(latest.get("html_url")) or None
        success_count = sum(run.get("conclusion") == "success" for run in completed)
        reliability = success_count / len(completed)
        return [
            HealthSignal(
                dimension=HealthDimension.CI, key="default_branch_ci",
                status=SignalStatus.PASS if conclusion == "success" else SignalStatus.FAIL,
                summary=f"Latest completed run concluded {conclusion}",
                evidence=EvidenceRef(source=source, summary=f"Latest conclusion: {conclusion}", observed_at=observed_at, url=url),
            ),
            HealthSignal(
                dimension=HealthDimension.CI, key="recent_ci_reliability",
                status=SignalStatus.PASS if reliability >= 0.8 else SignalStatus.FAIL,
                value=reliability, summary=f"{success_count} of {len(completed)} recent runs succeeded",
                evidence=EvidenceRef(source=source, summary=f"Recent success rate: {reliability:.0%}", observed_at=observed_at),
            ),
        ]

    async def _readme_signal(self, record: RepositoryRecord, observed_at: datetime) -> HealthSignal:
        exists = await self._github.readme_exists(record.owner, record.name)
        return HealthSignal(
            dimension=HealthDimension.DOCUMENTATION, key="readme_present",
            status=SignalStatus.PASS if exists else SignalStatus.FAIL,
            summary="README found" if exists else "README not found",
            evidence=EvidenceRef(
                source=f"github://{record.owner}/{record.name}/readme",
                summary="README endpoint returned content" if exists else "README endpoint returned not found",
                observed_at=observed_at,
            ),
        )
