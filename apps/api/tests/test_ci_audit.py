import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from maintainer_api.ci_audit import CiAuditService
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
        assert passed is True
        assert "actionlint binary not found" in output


@pytest.mark.asyncio
async def test_run_actionlint_subprocess_exception() -> None:
    service = CiAuditService()
    with patch("shutil.which", return_value="/bin/actionlint"), patch(
        "asyncio.create_subprocess_exec", side_effect=OSError("Exec error")
    ):
        passed, output = await service.run_actionlint()
        assert passed is True
        assert "Exec error" in output


@pytest.mark.asyncio
async def test_get_ci_audit() -> None:
    service = CiAuditService()
    mock_session = AsyncMock()
    mock_session.get.return_value = None

    summary = await service.get_ci_audit(mock_session, uuid4())
    assert summary.total_workflows >= 1
    assert len(summary.workflows) >= 1
    assert any(wf.path.endswith("ci.yml") for wf in summary.workflows)
    assert summary.jules_session is not None
    assert summary.jules_session.session_id == "9916342744409535567"


@pytest.mark.asyncio
async def test_ci_audit_endpoints() -> None:
    repo_id = uuid4()
    mock_session = AsyncMock()
    mock_session.get.return_value = None

    async def override_database_session():
        yield mock_session

    app.dependency_overrides[database_session] = override_database_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Summary endpoint
            res = await client.get("/api/v1/ci-audit/summary")
            assert res.status_code == 200
            data = res.json()
            assert "actionlint_passed" in data
            assert "workflows" in data
            assert data["total_workflows"] >= 1
            assert "jules_session" in data

            # Repo endpoint
            res_repo = await client.get(f"/api/v1/repositories/{repo_id}/ci-audit")
            assert res_repo.status_code == 200
            repo_data = res_repo.json()
            assert "actionlint_passed" in repo_data

            # Lint trigger endpoint
            res_lint = await client.post(f"/api/v1/repositories/{repo_id}/ci-audit/lint")
            assert res_lint.status_code == 200
            lint_data = res_lint.json()
            assert "actionlint_passed" in lint_data
    finally:
        app.dependency_overrides.pop(database_session, None)
