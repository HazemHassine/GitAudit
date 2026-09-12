from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from maintainer_api.ci_audit import CiAuditService
from maintainer_api.database import RepositoryRecord
from maintainer_api.main import app, database_session


@pytest.mark.asyncio
async def test_run_actionlint() -> None:
    service = CiAuditService()
    passed, output = await service.run_actionlint()
    assert isinstance(passed, bool)
    assert isinstance(output, str)
    assert len(output) > 0


@pytest.mark.asyncio
async def test_run_actionlint_missing_binary() -> None:
    service = CiAuditService()
    with patch("shutil.which", return_value=None), patch("pathlib.Path.is_file", return_value=False):
        passed, output = await service.run_actionlint()
        assert passed is False
        assert "actionlint binary not found" in output


@pytest.mark.asyncio
async def test_run_actionlint_subprocess_exception() -> None:
    service = CiAuditService()
    with patch("shutil.which", return_value="/bin/actionlint"), patch(
        "asyncio.create_subprocess_exec", side_effect=OSError("Exec error")
    ):
        passed, output = await service.run_actionlint()
        assert passed is False
        assert "Exec error" in output


@pytest.mark.asyncio
async def test_get_ci_audit() -> None:
    service = CiAuditService()
    mock_session = AsyncMock()

    # Remote/unknown repository returns unavailable scope and no local workflows
    mock_session.get.return_value = None
    summary_missing = await service.get_ci_audit(mock_session, uuid4())
    assert summary_missing.scope == "remote"
    assert summary_missing.total_workflows == 0
    assert summary_missing.jules_session is None

    # Local repository returns local workflows and session
    local_repo = RepositoryRecord(
        id=uuid4(),
        github_id=999,
        owner="HazemHassine",
        name="GitAudit",
        default_branch="main",
    )
    mock_session.get.return_value = local_repo
    summary_local = await service.get_ci_audit(mock_session, local_repo.id)
    assert summary_local.scope == "local"
    assert summary_local.total_workflows >= 1
    assert len(summary_local.workflows) >= 1
    assert any(wf.path.endswith("ci.yml") for wf in summary_local.workflows)
    assert summary_local.jules_session is None


def test_get_local_workflows_detects_both_yml_and_yaml(tmp_path: Path) -> None:
    service = CiAuditService()
    wf1 = tmp_path / "ci.yml"
    wf1.write_text("name: CI\n")
    wf2 = tmp_path / "deploy.yaml"
    wf2.write_text("name: Deploy\n")
    ignore = tmp_path / "readme.txt"
    ignore.write_text("hello\n")

    workflows = service._get_local_workflows(
        actionlint_ok=True, actionlint_out="OK", workflows_dir=tmp_path
    )
    assert len(workflows) == 2
    names = {w.name for w in workflows}
    assert "Ci" in names
    assert "Deploy" in names
    assert all(w.lint_status == "valid" for w in workflows)


@pytest.mark.asyncio
async def test_ci_audit_endpoints(monkeypatch) -> None:
    from pydantic import SecretStr

    from maintainer_api.main import settings
    monkeypatch.setattr(settings, "owner_password", SecretStr("fixture-owner-password"))
    mock_session = AsyncMock()
    mock_session.get.return_value = None

    async def override_database_session():
        yield mock_session

    app.dependency_overrides[database_session] = override_database_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer fixture-owner-password"}) as client:
            # Summary endpoint (local workspace GET and POST re-run)
            res = await client.get("/api/v1/ci-audit/summary")
            assert res.status_code == 200
            data = res.json()
            assert "actionlint_passed" in data
            assert "workflows" in data
            assert data["scope"] == "local"

            res_post = await client.post("/api/v1/ci-audit/summary")
            assert res_post.status_code == 200
            post_data = res_post.json()
            assert "workflows" in post_data
            assert post_data["scope"] == "local"

            # Non-existent repository (must return 404)
            missing_id = uuid4()
            res_missing = await client.get(f"/api/v1/repositories/{missing_id}/ci-audit")
            assert res_missing.status_code == 404

            # Remote repository
            remote_repo = RepositoryRecord(
                id=uuid4(),
                github_id=123,
                owner="acme",
                name="remote-app",
                default_branch="main",
            )
            mock_session.get.return_value = remote_repo
            res_remote = await client.get(f"/api/v1/repositories/{remote_repo.id}/ci-audit")
            assert res_remote.status_code == 200
            remote_data = res_remote.json()
            assert remote_data["scope"] == "remote"
            assert remote_data["workflows"] == []
            assert remote_data["jules_session"] is None

            # Local repository
            local_repo = RepositoryRecord(
                id=uuid4(),
                github_id=456,
                owner="HazemHassine",
                name="GitAudit",
                default_branch="main",
            )
            mock_session.get.return_value = local_repo
            res_local = await client.get(f"/api/v1/repositories/{local_repo.id}/ci-audit")
            assert res_local.status_code == 200
            local_data = res_local.json()
            assert local_data["scope"] == "local"
            assert local_data["total_workflows"] >= 1
            assert local_data["jules_session"] is None

            # Lint trigger endpoint for non-existent repo (404)
            mock_session.get.return_value = None
            res_lint_404 = await client.post(f"/api/v1/repositories/{missing_id}/ci-audit/lint")
            assert res_lint_404.status_code == 404

            # Lint trigger endpoint for local repo (200)
            mock_session.get.return_value = local_repo
            res_lint = await client.post(f"/api/v1/repositories/{local_repo.id}/ci-audit/lint")
            assert res_lint.status_code == 200
            lint_data = res_lint.json()
            assert lint_data["scope"] == "local"
    finally:
        app.dependency_overrides.pop(database_session, None)
