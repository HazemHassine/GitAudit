import base64

import httpx

from maintainer_api.config import Settings
from maintainer_api.github import GitHubEmptyRepositoryError, HttpGitHubReader


async def test_token_adapter_filters_actions_to_the_scanned_sha() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {"status": "completed", "conclusion": "success", "html_url": "run"}
                ]
            },
        )

    settings = Settings(
        _env_file=None,
        github_auth_mode="token",
        github_token="read-only-token",
        github_api_url="https://api.github.test",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = HttpGitHubReader(settings, client)
        runs = await reader.workflow_runs("acme", "widgets", "main", "abcdef")

    assert len(runs) == 1
    assert seen_request is not None
    assert seen_request.url.params["head_sha"] == "abcdef"
    assert seen_request.headers["authorization"] == "Bearer read-only-token"
    assert seen_request.headers["x-github-api-version"] == "2022-11-28"


async def test_github_app_exchanges_jwt_for_short_lived_installation_token(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        return httpx.Response(
            200,
            json={
                "repositories": [
                    {
                        "id": 101,
                        "owner": {"login": "acme"},
                        "name": "widgets",
                    }
                ]
            },
        )

    settings = Settings(
        _env_file=None,
        github_auth_mode="app",
        github_app_id="123",
        github_installation_id=456,
        github_app_private_key="unused-in-contract-test",
        github_api_url="https://api.github.test",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = HttpGitHubReader(settings, client)
        monkeypatch.setattr(reader, "_app_jwt", lambda: "signed-app-jwt")
        repositories = await reader.repositories()

    assert repositories[0]["name"] == "widgets"
    assert requests[0].headers["authorization"] == "Bearer signed-app-jwt"
    assert requests[1].headers["authorization"] == "Bearer installation-token"
    assert requests[1].url.path == "/installation/repositories"


async def test_empty_repository_commit_response_has_typed_outcome() -> None:
    settings = Settings(
        _env_file=None,
        github_auth_mode="token",
        github_token="read-only-token",
        github_api_url="https://api.github.test",
    )
    transport = httpx.MockTransport(lambda _: httpx.Response(409, json={"message": "Git Repository is empty."}))
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpGitHubReader(settings, client)
        try:
            await reader.default_branch("acme", "empty", "main")
        except GitHubEmptyRepositoryError as exc:
            assert "does not contain a commit" in str(exc)
        else:
            raise AssertionError("Expected a typed empty-repository outcome")


async def test_readme_content_is_decoded_for_curation_evidence() -> None:
    settings = Settings(
        _env_file=None,
        github_auth_mode="token",
        github_token="read-only-token",
        github_api_url="https://api.github.test",
    )
    encoded = base64.b64encode(b"# Widgets\n\nUseful widgets.").decode()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"encoding": "base64", "content": encoded})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpGitHubReader(settings, client)
        content = await reader.readme_content("acme", "widgets")

    assert content == "# Widgets\n\nUseful widgets."
