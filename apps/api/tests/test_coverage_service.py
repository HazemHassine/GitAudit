import unittest.mock
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from maintainer_api.config import Settings
from maintainer_api.coverage import CoverageService
from maintainer_api.database import RepositoryRecord
from maintainer_api.domain import GenerateTestsRequest
from maintainer_api.main import app, database_session


def test_coverage_service_fallback(tmp_path: Path) -> None:
    service = CoverageService()
    summary = service.get_coverage_summary(str(tmp_path / "non_existent_coverage.xml"))
    assert summary.status == "unavailable"
    assert summary.coverage_percent is None
    assert summary.passed_threshold is None
    assert summary.total_statements == 0
    assert summary.total_missed == 0
    assert summary.tests_passed is None
    assert summary.total_tests is None
    assert len(summary.modules) == 0
    assert summary.threshold_percent == 80.0
    assert summary.message is not None


def test_coverage_service_xml_parsing(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" ?>
<coverage version="7.16.0" timestamp="1757462000" lines-valid="100" lines-covered="85" line-rate="0.85">
    <packages>
        <package name="maintainer_api">
            <classes>
                <class name="service.py" filename="src/maintainer_api/service.py" line-rate="0.85" lines-covered="85" lines-valid="100">
                    <lines>
                        <line number="10" hits="1"/>
                        <line number="11" hits="0"/>
                    </lines>
                </class>
            </classes>
        </package>
    </packages>
</coverage>
"""
    xml_file = tmp_path / "coverage.xml"
    xml_file.write_text(xml_content)

    service = CoverageService()
    summary = service.get_coverage_summary(str(xml_file))
    assert summary.status == "available"
    assert summary.coverage_percent == 85.0
    assert summary.passed_threshold is True
    assert summary.total_statements == 100
    assert summary.total_missed == 15
    assert summary.tests_passed is None  # Honest: test counts not in coverage.xml
    assert summary.total_tests is None
    assert len(summary.modules) == 1
    assert summary.modules[0].name == "service.py"
    assert summary.modules[0].uncovered_lines == ["11"]


def test_coverage_service_cobertura_class_without_valid_attributes(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" ?>
<coverage version="7.16.0" lines-valid="10" lines-covered="8" line-rate="0.8">
    <packages>
        <package name="maintainer_api">
            <classes>
                <class name="activity.py" filename="src/maintainer_api/activity.py" line-rate="0.8">
                    <lines>
                        <line number="1" hits="1"/>
                        <line number="2" hits="1"/>
                        <line number="3" hits="1"/>
                        <line number="4" hits="1"/>
                        <line number="5" hits="0"/>
                    </lines>
                </class>
            </classes>
        </package>
    </packages>
</coverage>
"""
    xml_file = tmp_path / "cobertura.xml"
    xml_file.write_text(xml_content)

    service = CoverageService()
    summary = service.get_coverage_summary(str(xml_file))
    assert summary.status == "available"
    assert len(summary.modules) == 1
    mod = summary.modules[0]
    assert mod.name == "activity.py"
    assert mod.statements == 5
    assert mod.missed == 1
    assert mod.coverage_percent == 80.0
    assert mod.uncovered_lines == ["5"]


def test_coverage_service_invalid_numerical_ranges(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" ?>
<coverage lines-valid="10" lines-covered="20" line-rate="2.0">
    <packages></packages>
</coverage>
"""
    xml_file = tmp_path / "invalid_ranges.xml"
    xml_file.write_text(xml_content)

    service = CoverageService()
    summary = service.get_coverage_summary(str(xml_file))
    assert summary.status == "error"
    assert summary.coverage_percent is None


async def test_trigger_jules_test_generation_dry_run() -> None:
    service = CoverageService()
    req = GenerateTestsRequest(focus_module="curation.py", target_coverage=85.0, dry_run=True)
    session = await service.trigger_jules_test_generation(req)
    assert session.status == "preview"
    assert len(session.untested_cases) > 0
    assert session.pull_request_url is None


async def test_trigger_jules_test_generation_missing_api_key() -> None:
    import os
    service = CoverageService(Settings(jules_api_key=None))
    req = GenerateTestsRequest(focus_module="curation.py", target_coverage=85.0, dry_run=False)
    with unittest.mock.patch.dict(os.environ, {}, clear=True):
        session = await service.trigger_jules_test_generation(req)
        assert session.status == "unavailable"
        assert session.session_id == ""
        assert session.pull_request_url is None
        assert "not configured" in (session.plan_status or "").lower()


def test_coverage_service_corrupted_xml(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_coverage.xml"
    bad_file.write_text("<invalid xml")
    service = CoverageService()
    summary = service.get_coverage_summary(str(bad_file))
    assert summary.status == "error"
    assert summary.coverage_percent is None
    assert summary.passed_threshold is None
    assert summary.total_statements == 0
    assert summary.message is not None


@pytest.mark.skip(reason="Live Jules adapter verification is explicitly deferred.")
async def test_trigger_jules_test_generation_live_mock() -> None:
    import os
    service = CoverageService()
    req = GenerateTestsRequest(focus_module="curation.py", target_coverage=85.0, dry_run=False)

    mock_resp = unittest.mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = unittest.mock.Mock(return_value={"name": "sessions/mock-1234"})

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", return_value=mock_resp),
    ):
        session = await service.trigger_jules_test_generation(req)
        assert session.session_id == "sessions/mock-1234"
        assert session.status == "running"
        assert session.pull_request_url is None

    mock_err_resp = unittest.mock.MagicMock()
    mock_err_resp.status_code = 500
    mock_err_resp.text = "Internal error with sensitive secret"

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", return_value=mock_err_resp),
    ):
        session_err = await service.trigger_jules_test_generation(req)
        assert session_err.status == "failed"
        assert session_err.session_id == ""
        assert session_err.pull_request_url is None
        assert any("Error" in log for log in session_err.logs)
        assert "sensitive secret" not in str(session_err.logs)

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", side_effect=RuntimeError("internal secret")),
    ):
        session_exc = await service.trigger_jules_test_generation(req)
        assert session_exc.status == "failed"
        assert session_exc.session_id == ""
        assert session_exc.pull_request_url is None
        assert any("Error" in log for log in session_exc.logs)
        assert "internal secret" not in str(session_exc.logs)

    mock_empty_name_resp = unittest.mock.MagicMock()
    mock_empty_name_resp.status_code = 200
    mock_empty_name_resp.json = unittest.mock.Mock(return_value={})

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", return_value=mock_empty_name_resp),
    ):
        session_no_name = await service.trigger_jules_test_generation(req)
        assert session_no_name.status == "failed"
        assert session_no_name.session_id == ""


async def test_stream_events() -> None:
    service = CoverageService()
    generator = service.stream_events()
    first_event = await anext(generator)
    assert "event: coverage_snapshot" in first_event

    await service._broadcast_event("session_update", '{"status": "ok"}')
    second_event = await anext(generator)
    assert "event: session_update" in second_event
    await generator.aclose()


async def test_api_coverage_endpoints() -> None:
    mock_session = AsyncMock()
    mock_session.get.return_value = None

    async def override_database_session():
        yield mock_session

    app.dependency_overrides[database_session] = override_database_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # GET summary (local workspace)
            res = await client.get("/api/v1/coverage/summary")
            assert res.status_code == 200
            data = res.json()
            assert "threshold_percent" in data
            assert data["threshold_percent"] == 80.0
            assert "status" in data
            assert data["scope"] == "local"

            # POST generate-tests dry-run
            res_gen = await client.post(
                "/api/v1/coverage/generate-tests",
                json={"focus_module": "curation.py", "dry_run": True},
            )
            assert res_gen.status_code == 200
            gen_data = res_gen.json()
            assert "session_id" in gen_data
            assert gen_data["status"] == "preview"
            assert gen_data["pull_request_url"] is None

            # GET repository coverage for non-existent repository (must 404)
            res_repo_404 = await client.get(
                "/api/v1/repositories/00000000-0000-0000-0000-000000000001/coverage"
            )
            assert res_repo_404.status_code == 404

            # GET repository coverage for remote repository
            remote_repo = RepositoryRecord(
                id=uuid4(),
                github_id=12345,
                owner="acme",
                name="remote-project",
                default_branch="main",
            )
            mock_session.get.return_value = remote_repo
            res_repo_remote = await client.get(f"/api/v1/repositories/{remote_repo.id}/coverage")
            assert res_repo_remote.status_code == 200
            remote_data = res_repo_remote.json()
            assert remote_data["scope"] == "remote"
            assert remote_data["status"] == "unavailable"
            assert remote_data["coverage_percent"] is None
            assert "Local coverage evidence is not available" in remote_data["message"]

            # GET repository coverage for local repository
            local_repo = RepositoryRecord(
                id=uuid4(),
                github_id=67890,
                owner="HazemHassine",
                name="GitAudit",
                default_branch="main",
            )
            mock_session.get.return_value = local_repo
            res_repo_local = await client.get(f"/api/v1/repositories/{local_repo.id}/coverage")
            assert res_repo_local.status_code == 200
            local_data = res_repo_local.json()
            assert local_data["scope"] == "local"
    finally:
        app.dependency_overrides.pop(database_session, None)
