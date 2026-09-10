from pathlib import Path

from httpx import ASGITransport, AsyncClient

from maintainer_api.coverage import CoverageService
from maintainer_api.domain import GenerateTestsRequest
from maintainer_api.main import app


def test_coverage_service_fallback() -> None:
    service = CoverageService()
    summary = service.get_coverage_summary("non_existent_coverage.xml")
    assert summary.threshold_percent == 80.0
    assert summary.coverage_percent >= 0.0
    assert summary.total_statements > 0
    assert len(summary.modules) > 0


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
    assert summary.coverage_percent == 85.0
    assert summary.passed_threshold is True
    assert summary.total_statements == 100
    assert summary.total_missed == 15
    assert len(summary.modules) == 1
    assert summary.modules[0].name == "service.py"
    assert summary.modules[0].uncovered_lines == ["11"]


async def test_trigger_jules_test_generation_dry_run() -> None:
    service = CoverageService()
    req = GenerateTestsRequest(focus_module="curation.py", target_coverage=85.0, dry_run=True)
    session = await service.trigger_jules_test_generation(req)
    assert session.status == "running"
    assert len(session.untested_cases) > 0
    assert session.pull_request_url is not None


def test_coverage_service_corrupted_xml(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_coverage.xml"
    bad_file.write_text("<invalid xml")
    service = CoverageService()
    summary = service.get_coverage_summary(str(bad_file))
    assert summary.coverage_percent == 81.5


async def test_trigger_jules_test_generation_live_mock() -> None:
    import os
    import unittest.mock
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

    mock_err_resp = unittest.mock.MagicMock()
    mock_err_resp.status_code = 500
    mock_err_resp.text = "Internal error"

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", return_value=mock_err_resp),
    ):
        session_err = await service.trigger_jules_test_generation(req)
        assert session_err.status == "completed"

    with (
        unittest.mock.patch.dict(os.environ, {"JULES_API_KEY": "fake-key"}),
        unittest.mock.patch("httpx.AsyncClient.post", side_effect=RuntimeError("network error")),
    ):
        session_exc = await service.trigger_jules_test_generation(req)
        assert session_exc.status == "completed"


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET summary
        res = await client.get("/api/v1/coverage/summary")
        assert res.status_code == 200
        data = res.json()
        assert "coverage_percent" in data
        assert data["threshold_percent"] == 80.0

        # POST generate-tests dry-run
        res_gen = await client.post(
            "/api/v1/coverage/generate-tests",
            json={"focus_module": "curation.py", "dry_run": True},
        )
        assert res_gen.status_code == 200
        gen_data = res_gen.json()
        assert "session_id" in gen_data

        # GET repository coverage
        res_repo = await client.get("/api/v1/repositories/00000000-0000-0000-0000-000000000001/coverage")
        assert res_repo.status_code == 200

