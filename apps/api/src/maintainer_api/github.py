from typing import Protocol

import httpx

from .config import Settings


class GitHubError(RuntimeError):
    pass


class GitHubReader(Protocol):
    async def authenticated_user(self) -> dict[str, object]: ...
    async def repositories(self) -> list[dict[str, object]]: ...
    async def repository(self, owner: str, name: str) -> dict[str, object]: ...
    async def default_branch(self, owner: str, name: str, branch: str) -> dict[str, object]: ...
    async def workflow_runs(self, owner: str, name: str, branch: str) -> list[dict[str, object]]: ...
    async def readme_exists(self, owner: str, name: str) -> bool: ...


class HttpGitHubReader:
    """Read-only GitHub boundary. Tokens are never logged or returned."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._base_url = str(settings.github_api_url).rstrip("/")
        self._client = client
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {settings.github_token}"} if settings.github_token else {}),
        }

    async def _response(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        response = await self._client.get(f"{self._base_url}{path}", headers=self._headers, params=params)
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError("GitHub rate limit exhausted; retry after the reset time")
        return response

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
        response = await self._response(path, params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubError(f"GitHub returned HTTP {response.status_code}") from exc
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected response shape")
        return data

    async def authenticated_user(self) -> dict[str, object]:
        return await self._get("/user")

    async def repositories(self) -> list[dict[str, object]]:
        repositories: list[dict[str, object]] = []
        page = 1
        while True:
            response = await self._response(
                "/user/repos",
                {"affiliation": "owner,collaborator,organization_member", "sort": "updated", "per_page": "100", "page": str(page)},
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise GitHubError(f"GitHub returned HTTP {response.status_code}") from exc
            data = response.json()
            if not isinstance(data, list):
                raise GitHubError("GitHub returned an unexpected repository list")
            batch = [item for item in data if isinstance(item, dict)]
            repositories.extend(batch)
            if len(batch) < 100:
                return repositories
            page += 1

    async def repository(self, owner: str, name: str) -> dict[str, object]:
        return await self._get(f"/repos/{owner}/{name}")

    async def default_branch(self, owner: str, name: str, branch: str) -> dict[str, object]:
        return await self._get(f"/repos/{owner}/{name}/commits/{branch}")

    async def workflow_runs(self, owner: str, name: str, branch: str) -> list[dict[str, object]]:
        data = await self._get(f"/repos/{owner}/{name}/actions/runs", {"branch": branch, "per_page": "20"})
        runs = data.get("workflow_runs", [])
        return runs if isinstance(runs, list) else []

    async def readme_exists(self, owner: str, name: str) -> bool:
        response = await self._response(f"/repos/{owner}/{name}/readme")
        if response.status_code == 404:
            return False
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubError(f"GitHub returned HTTP {response.status_code} while reading README") from exc
        return True
