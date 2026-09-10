from maintainer_api.main import app, healthcheck


async def test_healthcheck() -> None:
    assert (await healthcheck())["status"] == "ok"


def test_openapi_exposes_scans_and_proposal_only_curation_resources() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/github/repositories" in paths
    assert "/api/v1/repositories/{repository_id}/scans" in paths
    assert "/api/v1/repositories/{repository_id}/scans/{scan_id}" in paths
    assert "/api/v1/sync" in paths
    assert "/api/v1/settings/github" in paths
    assert "/api/v1/settings/ai" in paths
    assert "/api/v1/repositories/{repository_id}/assessments" in paths
    assert "/api/v1/coverage/summary" in paths
    assert "/api/v1/coverage/generate-tests" in paths
    assert "/api/v1/coverage/stream" in paths
    assert "/api/v1/repositories/{repository_id}/coverage" in paths
    assert "/api/v1/ci-audit/summary" in paths
    assert "/api/v1/repositories/{repository_id}/ci-audit" in paths
    assert "/api/v1/repositories/{repository_id}/ci-audit/lint" in paths
    # DELETE excludes a repository locally; no GitHub mutation endpoint exists.
    assert "delete" in paths["/api/v1/repositories/{repository_id}"]
    assert not any("apply" in path or "approve" in path for path in paths)


async def test_metrics_endpoint() -> None:
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert "http_requests_total" in res.text


async def test_settings_endpoints() -> None:
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res_gh = await client.get("/api/v1/settings/github")
        assert res_gh.status_code == 200
        assert "configured" in res_gh.json()

        res_ai = await client.get("/api/v1/settings/ai")
        assert res_ai.status_code == 200
        assert "configured" in res_ai.json()


async def test_exception_handlers() -> None:
    from starlette.requests import Request

    from maintainer_api.curation import (
        AssessmentInProgressError,
        CurationConfigurationError,
        CurationError,
    )
    from maintainer_api.github import GitHubConfigurationError, GitHubError
    from maintainer_api.main import (
        curation_error_handler,
        github_error_handler,
        scan_in_progress_handler,
    )
    from maintainer_api.service import ScanInProgressError

    dummy_request = Request({"type": "http", "method": "GET", "path": "/"})

    res = await github_error_handler(dummy_request, GitHubConfigurationError("Config missing"))
    assert res.status_code == 503

    res2 = await github_error_handler(dummy_request, GitHubError("Generic GitHub error"))
    assert res2.status_code == 502

    res3 = await scan_in_progress_handler(dummy_request, ScanInProgressError("Scan in progress"))
    assert res3.status_code == 409

    res4 = await curation_error_handler(dummy_request, AssessmentInProgressError("Assessment active"))
    assert res4.status_code == 409

    res5 = await curation_error_handler(dummy_request, CurationConfigurationError("OpenAI missing"))
    assert res5.status_code == 503

    res6 = await curation_error_handler(dummy_request, CurationError("Generic AI error"))
    assert res6.status_code == 502

