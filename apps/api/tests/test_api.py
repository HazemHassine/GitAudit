from maintainer_api.main import app, healthcheck


async def test_healthcheck() -> None:
    assert (await healthcheck())["status"] == "ok"


def test_openapi_exposes_read_only_milestone_one_resources() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/github/repositories" in paths
    assert "/api/v1/repositories/{repository_id}/scans" in paths
    assert "/api/v1/repositories/{repository_id}/scans/{scan_id}" in paths
    assert "/api/v1/sync" in paths
    assert "/api/v1/settings/github" in paths
    # DELETE excludes a repository locally; no GitHub mutation endpoint exists.
    assert "delete" in paths["/api/v1/repositories/{repository_id}"]
