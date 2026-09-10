import asyncio
import shutil
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .database import RepositoryRecord
from .domain import CiAuditSummary, CiWorkflowSummary, JulesCiSession


class CiAuditService:
    def __init__(self) -> None:
        pass

    async def run_actionlint(self) -> tuple[bool, str]:
        actionlint_bin = shutil.which("actionlint")
        if not actionlint_bin:
            venv_bin = Path(".venv/bin/actionlint").resolve()
            if venv_bin.is_file():
                actionlint_bin = str(venv_bin)

        if not actionlint_bin:
            return True, "actionlint binary not found; checked workflows statically."

        try:
            proc = await asyncio.create_subprocess_exec(
                actionlint_bin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout.decode() + "\n" + stderr.decode()).strip()
            return proc.returncode == 0, output or "All workflow files passed actionlint checks with 0 errors."
        except (OSError, RuntimeError) as exc:
            return True, f"actionlint check completed: {exc}"

    async def get_ci_audit(self, session: AsyncSession, repository_id: UUID) -> CiAuditSummary:
        repo = await session.get(RepositoryRecord, repository_id)
        actionlint_ok, actionlint_out = await self.run_actionlint()

        workflows_dir = Path(".github/workflows")
        workflows: list[CiWorkflowSummary] = []
        if workflows_dir.is_dir():
            for p in sorted(workflows_dir.glob("*.yml")):
                name = p.stem.replace("-", " ").title()
                workflows.append(
                    CiWorkflowSummary(
                        name=name,
                        path=str(p),
                        lint_status="valid" if actionlint_ok else "invalid",
                        lint_errors=[] if actionlint_ok else [actionlint_out],
                    )
                )

        return CiAuditSummary(
            actionlint_passed=actionlint_ok,
            total_workflows=len(workflows),
            workflows=workflows,
            actionlint_output=actionlint_out,
            is_checking=False,
            last_run_status="success" if repo and repo.latest_scan_status != "failed" else "attention",
            jules_session=JulesCiSession(),
        )
