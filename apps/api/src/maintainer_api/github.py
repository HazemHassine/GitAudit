import asyncio
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx
import jwt

from .config import Settings


class GitHubError(RuntimeError):
    pass


class GitHubConfigurationError(GitHubError):
    pass


class GitHubEmptyRepositoryError(GitHubError):
    pass


class GitHubReader(Protocol):
    async def authenticated_user(self) -> dict[str, object]: ...
    async def repositories(self) -> list[dict[str, object]]: ...
    async def repository(self, owner: str, name: str) -> dict[str, object]: ...
    async def default_branch(self, owner: str, name: str, branch: str) -> dict[str, object]: ...
    async def check_runs(self, owner: str, name: str, sha: str) -> list[dict[str, object]]: ...
    async def workflow_runs(
        self, owner: str, name: str, branch: str, head_sha: str | None = None
    ) -> list[dict[str, object]]: ...
    async def workflow_run_jobs(self, owner: str, name: str, run_id: int) -> list[dict[str, object]]: ...
    async def job_logs(self, owner: str, name: str, job_id: int) -> str: ...
    async def readme_exists(self, owner: str, name: str) -> bool: ...
    async def readme_content(self, owner: str, name: str) -> str | None: ...
    async def commit_activity(self, owner: str, name: str) -> list[dict[str, object]]: ...
    async def punch_card(self, owner: str, name: str) -> list[list[int]]: ...
    async def recent_commits(self, owner: str, name: str, branch: str, count: int = 30) -> list[dict[str, object]]: ...
    async def user_events(self, login: str, count: int = 50) -> list[dict[str, object]]: ...
    async def contribution_calendar(self, login: str) -> dict[str, object]: ...


class HttpGitHubReader:
    """Read-only GitHub boundary supporting PATs and installation tokens."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._base_url = str(settings.github_api_url).rstrip("/")
        self._client = client
        self._installation_token: str | None = None
        self._installation_token_expires_at: datetime | None = None
        self._token_lock = asyncio.Lock()

    def _app_private_key(self) -> str:
        if self._settings.github_app_private_key:
            return self._settings.github_app_private_key.get_secret_value().replace("\\n", "\n")
        if self._settings.github_app_private_key_path:
            try:
                return Path(self._settings.github_app_private_key_path).read_text()
            except OSError as exc:
                raise GitHubConfigurationError("Unable to read the GitHub App private key") from exc
        raise GitHubConfigurationError("GitHub App private key is not configured")

    def _app_jwt(self) -> str:
        if not self._settings.github_app_id:
            raise GitHubConfigurationError("GitHub App ID is not configured")
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "iat": int((now - timedelta(seconds=30)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": self._settings.github_app_id,
            },
            self._app_private_key(),
            algorithm="RS256",
        )

    async def _app_installation_token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._installation_token
            and self._installation_token_expires_at
            and self._installation_token_expires_at > now + timedelta(minutes=1)
        ):
            return self._installation_token
        async with self._token_lock:
            now = datetime.now(UTC)
            if (
                self._installation_token
                and self._installation_token_expires_at
                and self._installation_token_expires_at > now + timedelta(minutes=1)
            ):
                return self._installation_token
            installation_id = self._settings.github_installation_id
            if installation_id is None:
                raise GitHubConfigurationError("GitHub App installation ID is not configured")
            response = await self._client.post(
                f"{self._base_url}/app/installations/{installation_id}/access_tokens",
                headers=self._base_headers(f"Bearer {self._app_jwt()}"),
            )
            self._raise_for_status(response, "creating an installation token")
            data = response.json()
            token = data.get("token") if isinstance(data, dict) else None
            expires_at = data.get("expires_at") if isinstance(data, dict) else None
            if not isinstance(token, str) or not isinstance(expires_at, str):
                raise GitHubError("GitHub returned an invalid installation token response")
            self._installation_token = token
            self._installation_token_expires_at = datetime.fromisoformat(expires_at)
            return token

    @staticmethod
    def _base_headers(authorization: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if authorization:
            headers["Authorization"] = authorization
        return headers

    async def _headers(self, *, app: bool = False) -> dict[str, str]:
        mode = self._settings.resolved_github_auth_mode
        if app:
            if mode != "app":
                raise GitHubConfigurationError("GitHub App authentication is not configured")
            return self._base_headers(f"Bearer {self._app_jwt()}")
        if mode == "app":
            return self._base_headers(f"Bearer {await self._app_installation_token()}")
        if mode == "token" and self._settings.github_token:
            token = self._settings.github_token.get_secret_value()
            return self._base_headers(f"Bearer {token}")
        raise GitHubConfigurationError(
            "GitHub is not configured; add a GitHub App installation or a fine-grained token"
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response, context: str = "reading GitHub") -> None:
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset")
            reset_message = f"; resets at Unix time {reset}" if reset else ""
            raise GitHubError(f"GitHub rate limit exhausted{reset_message}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubError(
                f"GitHub returned HTTP {response.status_code} while {context}"
            ) from exc

    async def _response(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        app: bool = False,
    ) -> httpx.Response:
        return await self._client.get(
            f"{self._base_url}{path}", headers=await self._headers(app=app), params=params
        )

    async def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        app: bool = False,
    ) -> dict[str, object]:
        response = await self._response(path, params, app=app)
        self._raise_for_status(response)
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected response shape")
        return data

    async def authenticated_user(self) -> dict[str, object]:
        if self._settings.resolved_github_auth_mode == "app":
            installation_id = self._settings.github_installation_id
            if installation_id is None:
                raise GitHubConfigurationError("GitHub App installation ID is not configured")
            data = await self._get(f"/app/installations/{installation_id}", app=True)
            account = data.get("account")
            if not isinstance(account, dict):
                raise GitHubError("GitHub installation response did not contain an account")
            return account
        return await self._get("/user")

    async def repositories(self) -> list[dict[str, object]]:
        repositories: list[dict[str, object]] = []
        page = 1
        while True:
            if self._settings.resolved_github_auth_mode == "app":
                response = await self._response(
                    "/installation/repositories", {"per_page": "100", "page": str(page)}
                )
                self._raise_for_status(response)
                payload = response.json()
                raw_batch = payload.get("repositories", []) if isinstance(payload, dict) else []
            else:
                response = await self._response(
                    "/user/repos",
                    {
                        "affiliation": "owner,collaborator,organization_member",
                        "sort": "updated",
                        "per_page": "100",
                        "page": str(page),
                    },
                )
                self._raise_for_status(response)
                raw_batch = response.json()
            if not isinstance(raw_batch, list):
                raise GitHubError("GitHub returned an unexpected repository list")
            batch = [item for item in raw_batch if isinstance(item, dict)]
            repositories.extend(batch)
            if len(batch) < 100:
                return repositories
            page += 1

    async def repository(self, owner: str, name: str) -> dict[str, object]:
        return await self._get(f"/repos/{owner}/{name}")

    async def default_branch(self, owner: str, name: str, branch: str) -> dict[str, object]:
        response = await self._response(f"/repos/{owner}/{name}/commits/{branch}")
        if response.status_code == 409:
            raise GitHubEmptyRepositoryError("Repository does not contain a commit yet")
        self._raise_for_status(response)
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected commit response")
        return data

    async def check_runs(self, owner: str, name: str, sha: str) -> list[dict[str, object]]:
        data = await self._get(
            f"/repos/{owner}/{name}/commits/{sha}/check-runs", {"per_page": "100"}
        )
        runs = data.get("check_runs", [])
        return [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []

    async def workflow_runs(
        self, owner: str, name: str, branch: str, head_sha: str | None = None
    ) -> list[dict[str, object]]:
        params = {"branch": branch, "per_page": "20"}
        if head_sha:
            params["head_sha"] = head_sha
        data = await self._get(f"/repos/{owner}/{name}/actions/runs", params)
        runs = data.get("workflow_runs", [])
        return [item for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []

    async def workflow_run_jobs(self, owner: str, name: str, run_id: int) -> list[dict[str, object]]:
        data = await self._get(f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs")
        jobs = data.get("jobs", [])
        return [item for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []

    async def job_logs(self, owner: str, name: str, job_id: int) -> str:
        response = await self._response(f"/repos/{owner}/{name}/actions/jobs/{job_id}/logs")
        if response.status_code == 404:
            return ""
        self._raise_for_status(response, "reading job logs")
        return response.text

    async def readme_exists(self, owner: str, name: str) -> bool:
        response = await self._response(f"/repos/{owner}/{name}/readme")
        if response.status_code == 404:
            return False
        self._raise_for_status(response, "reading the README")
        return True

    async def readme_content(self, owner: str, name: str) -> str | None:
        response = await self._response(f"/repos/{owner}/{name}/readme")
        if response.status_code == 404:
            return None
        self._raise_for_status(response, "reading the README")
        payload = response.json()
        content = payload.get("content") if isinstance(payload, dict) else None
        encoding = payload.get("encoding") if isinstance(payload, dict) else None
        if not isinstance(content, str) or encoding != "base64":
            raise GitHubError("GitHub returned an invalid README response")
        try:
            return base64.b64decode(content, validate=False).decode("utf-8", errors="replace")
        except ValueError as exc:
            raise GitHubError("GitHub returned invalid README content") from exc

    async def _get_stats(self, path: str) -> list | dict:
        """Fetch GitHub stats endpoint with 202 retry."""
        for attempt in range(4):
            response = await self._response(path)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 202 and attempt < 3:
                await asyncio.sleep(2)
                continue
            self._raise_for_status(response)
        return []

    async def commit_activity(self, owner: str, name: str) -> list[dict[str, object]]:
        data = await self._get_stats(f"/repos/{owner}/{name}/stats/commit_activity")
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    async def punch_card(self, owner: str, name: str) -> list[list[int]]:
        data = await self._get_stats(f"/repos/{owner}/{name}/stats/punch_card")
        return [item for item in data if isinstance(item, list)] if isinstance(data, list) else []

    async def recent_commits(self, owner: str, name: str, branch: str, count: int = 30) -> list[dict[str, object]]:
        data = await self._get(f"/repos/{owner}/{name}/commits", {"sha": branch, "per_page": str(count)})
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    async def user_events(self, login: str, count: int = 50) -> list[dict[str, object]]:
        data = await self._get(f"/users/{login}/events", {"per_page": str(count)})
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    async def contribution_calendar(self, login: str) -> dict[str, object]:
        if self._settings.resolved_github_auth_mode == "app":
            raise GitHubError("GraphQL contribution calendar requires a PAT, app authentication is not supported")
        query = {
            "query": f'{{ user(login: "{login}") {{ contributionsCollection {{ contributionCalendar {{ totalContributions weeks {{ contributionDays {{ date contributionCount color }} }} }} }} }} }}'
        }
        response = await self._client.post(
            f"{self._base_url}/graphql",
            headers=await self._headers(app=False),
            json=query,
        )
        self._raise_for_status(response, "fetching contribution calendar")
        data = response.json()
        if not isinstance(data, dict):
            raise GitHubError("GitHub returned an unexpected GraphQL response")
        return data
