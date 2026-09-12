import asyncio
import shutil
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .database import RepositoryRecord
from .domain import (
    CiAuditSummary,
    CiWorkflowSummary,
    CreateJulesSessionRequest,
    JulesAuditArea,
    JulesCiSession,
    TriggerCiAnalysisRequest,
)
from .jules import JulesAuditService


class CiAuditService:
    def __init__(self, jules_service: JulesAuditService | None = None) -> None:
        self.jules_service = jules_service or JulesAuditService()

    @staticmethod
    def is_local_repository(owner: str, name: str) -> bool:
        full = f"{owner}/{name}".lower()
        return full in ("hazemhassine/github_maintainer", "hazemhassine/gitaudit")

    async def run_actionlint(self) -> tuple[bool, str]:
        actionlint_bin = shutil.which("actionlint")
        if not actionlint_bin:
            candidates = [
                Path(".venv/bin/actionlint"),
                Path("apps/api/.venv/bin/actionlint"),
                Path(__file__).resolve().parents[4] / ".venv/bin/actionlint",
                Path(__file__).resolve().parents[2] / ".venv/bin/actionlint",
            ]
            for c in candidates:
                if c.is_file():
                    actionlint_bin = str(c)
                    break

        if not actionlint_bin:
            return False, "actionlint binary not found in PATH or .venv/bin/actionlint."

        try:
            proc = await asyncio.create_subprocess_exec(
                actionlint_bin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout.decode() + "\n" + stderr.decode()).strip()
            passed = proc.returncode == 0
            return passed, output or "All workflow files passed actionlint checks with 0 errors."
        except (OSError, RuntimeError) as exc:
            return False, f"actionlint execution failed: {exc}"

    def _get_local_workflows(
        self,
        actionlint_ok: bool,
        actionlint_out: str,
        workflows_dir: Path | None = None,
    ) -> list[CiWorkflowSummary]:
        if workflows_dir is None:
            candidates = [
                Path(".github/workflows"),
                Path(__file__).resolve().parents[4] / ".github/workflows",
                Path(__file__).resolve().parents[2] / ".github/workflows",
            ]
            for c in candidates:
                if c.is_dir():
                    workflows_dir = c
                    break
            if workflows_dir is None:
                workflows_dir = Path(".github/workflows")

        workflows: list[CiWorkflowSummary] = []
        if workflows_dir.is_dir():
            workflow_files = sorted({
                p
                for p in workflows_dir.iterdir()
                if p.is_file() and p.suffix in (".yml", ".yaml")
            })
            for p in workflow_files:
                name = p.stem.replace("-", " ").title()
                if "binary not found" in actionlint_out:
                    lint_status = "unavailable"
                    lint_errors = ["actionlint binary not found in PATH or .venv/bin/actionlint"]
                elif "execution failed" in actionlint_out:
                    lint_status = "error"
                    lint_errors = [actionlint_out]
                elif actionlint_ok:
                    lint_status = "valid"
                    lint_errors = []
                else:
                    lint_status = "invalid"
                    lint_errors = [actionlint_out]

                workflows.append(
                    CiWorkflowSummary(
                        name=name,
                        path=str(p),
                        lint_status=lint_status,
                        lint_errors=lint_errors,
                    )
                )
        return workflows

    async def get_local_ci_audit(
        self, workflows_dir: Path | None = None
    ) -> CiAuditSummary:
        actionlint_ok, actionlint_out = await self.run_actionlint()
        workflows = self._get_local_workflows(
            actionlint_ok, actionlint_out, workflows_dir=workflows_dir
        )

        if "binary not found" in actionlint_out:
            last_run_status = "unavailable"
        elif "execution failed" in actionlint_out:
            last_run_status = "error"
        elif actionlint_ok:
            last_run_status = "success"
        else:
            last_run_status = "failed"

        return CiAuditSummary(
            actionlint_passed=actionlint_ok,
            total_workflows=len(workflows),
            workflows=workflows,
            actionlint_output=actionlint_out,
            is_checking=False,
            last_run_status=last_run_status,
            jules_session=None,
            scope="local",
            message=None,
        )

    async def get_ci_audit_for_repository(
        self, repo: RepositoryRecord | None
    ) -> CiAuditSummary:
        if repo is None:
            return CiAuditSummary(
                actionlint_passed=False,
                total_workflows=0,
                workflows=[],
                actionlint_output="Repository not found.",
                is_checking=False,
                last_run_status="unavailable",
                jules_session=None,
                scope="remote",
                message="Repository not found.",
            )

        if not self.is_local_repository(repo.owner, repo.name):
            return CiAuditSummary(
                actionlint_passed=None,
                total_workflows=0,
                workflows=[],
                actionlint_output=(
                    f"Local workflow files and actionlint checks are not available for "
                    f"remote repository '{repo.owner}/{repo.name}'."
                ),
                is_checking=False,
                last_run_status="unavailable",
                jules_session=None,
                scope="remote",
                message=(
                    f"Local CI audit evidence is restricted to the local repository workspace. "
                    f"Remote repository '{repo.owner}/{repo.name}' requires workflow inspection via GitHub API."
                ),
            )

        summary = await self.get_local_ci_audit()
        if repo.latest_scan_status == "failed" and summary.last_run_status == "success":
            summary.last_run_status = "attention"
        return summary

    async def get_ci_audit(self, session: AsyncSession, repository_id: UUID) -> CiAuditSummary:
        if str(repository_id) == "00000000-0000-0000-0000-000000000000":
            return await self.get_local_ci_audit()

        repo = await session.get(RepositoryRecord, repository_id)
        return await self.get_ci_audit_for_repository(repo)

    async def trigger_jules_analysis(self, request: TriggerCiAnalysisRequest) -> JulesCiSession:
        """Compatibility route backed by the shared Jules audit session service."""
        session = await self.jules_service.create_session(
            CreateJulesSessionRequest(
                audit_area=JulesAuditArea.CI,
                focus=request.focus,
                dry_run=request.dry_run,
                idempotency_key=request.idempotency_key,
            )
        )
        return JulesCiSession(
            session_id=session.session_id,
            status=session.status.value,
            plan_status=session.plan_status,
            url=session.url,
            pull_request_url=session.pull_request_url,
            logs=session.activity,
        )
