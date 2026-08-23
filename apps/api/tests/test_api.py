from fastapi.testclient import TestClient

from maintainer_api.main import app


def test_healthcheck() -> None:
    assert TestClient(app).get("/healthz").json()["status"] == "ok"


def test_openapi_exposes_read_only_milestone_one_resources() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/v1/github/repositories" in paths
    assert "/api/v1/repositories/{repository_id}/scans" in paths
    assert "delete" not in paths["/api/v1/repositories/{repository_id}"]
