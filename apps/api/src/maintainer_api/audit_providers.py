"""Trusted provider boundaries; repository execution never receives API credentials."""

import re
from urllib.parse import quote

import httpx

from .config import Settings
from .github import HttpGitHubReader
from .sandbox import MAX_SOURCE, SandboxError


class ProviderError(RuntimeError):
    """Provider rejection with enough status information for conservative retries."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class JulesClient:
    """Actual source discovery, plan approvals and activity artifact retrieval."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def request(
        self, method: str, path: str, payload: dict | None = None, params: dict | None = None
    ) -> dict:
        """Make one request without automatic mutation retries."""
        if not self.settings.jules_api_key:
            raise ProviderError("Jules connection required", 401)
        if not re.fullmatch(
            r"(?:sources|sessions)(?:/[A-Za-z0-9_-]+)?(?:/activities|:approvePlan|:sendMessage)?",
            path,
        ):
            raise ProviderError("Invalid Jules resource")
        response = await self.client.request(
            method,
            f"https://jules.googleapis.com/v1alpha/{path}",
            headers={"X-Goog-Api-Key": self.settings.jules_api_key.get_secret_value()},
            json=payload,
            params=params,
        )
        if response.is_error:
            raise ProviderError(f"Jules returned HTTP {response.status_code}", response.status_code)
        return response.json() if response.content else {}

    async def pages(self, path: str, key: str) -> list[dict]:
        """Read all pages, rejecting repeated cursors rather than silently truncating."""
        items, seen, token = [], set(), ""
        while True:
            data = await self.request("GET", path, params={"pageSize": 100, "pageToken": token})
            items.extend(data.get(key, []))
            token = data.get("nextPageToken", "")
            if not token:
                return items
            if token in seen:
                raise ProviderError("Repeated Jules pagination cursor")
            seen.add(token)

    async def source(self, owner: str, repository: str) -> str:
        """Resolve the opaque identifier returned by Sources API."""
        for source in await self.pages("sources", "sources"):
            repo = source.get("githubRepo", {})
            if (str(repo.get("owner", "")).lower(), str(repo.get("repo", "")).lower()) == (
                owner.lower(),
                repository.lower(),
            ):
                return source["name"]
        raise ProviderError(
            "Connect this repository in Jules; deterministic auditing remains available", 404
        )

    async def create(self, source: str, branch: str, marker: str, prompt: str) -> dict:
        """Create exactly once after the backend reserves quota; disable automatic PRs."""
        return await self.request(
            "POST",
            "sessions",
            {
                "title": marker,
                "prompt": prompt,
                "requirePlanApproval": True,
                "automationMode": "AUTOMATION_MODE_UNSPECIFIED",
                "sourceContext": {
                    "source": source,
                    "githubRepoContext": {"startingBranch": branch},
                },
            },
        )

    async def activities(self, name: str) -> list[dict]:
        """Retrieve durable real plans, activity and patches in chronological order."""
        return sorted(
            await self.pages(f"{name}/activities", "activities"),
            key=lambda a: (a.get("createTime", ""), a.get("name", "")),
        )


class GitHubAuditClient:
    """Read recorded commits and publish through GitHub's Git data and PR APIs."""

    def __init__(self, reader: HttpGitHubReader):
        self.reader = reader

    async def request(
        self,
        method: str,
        repo: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict | list:
        """Use trusted authentication only on the configured GitHub API origin."""
        subpath = f"/{path.lstrip('/')}" if path else ""
        response = await self.reader._client.request(
            method,
            f"{self.reader._base_url}/repos/{repo}{subpath}",
            headers=await self.reader._headers(),
            json=data,
            params=params,
        )
        if response.is_error:
            target = path.strip("/").split("/")[0] if path.strip("/") else "repository"
            raise ProviderError(
                f"GitHub {target} returned HTTP {response.status_code}",
                response.status_code,
            )
        return response.json() if response.content else {}

    async def head(self, repo: str) -> tuple[str, str]:
        """Resolve the current default branch and its immutable commit."""
        metadata = await self.request("GET", repo, "")
        branch = metadata["default_branch"]
        commit = await self.request("GET", repo, f"commits/{quote(branch, safe='')}")
        return branch, commit["sha"]

    async def archive(self, repo: str, sha: str) -> bytes:
        """Download source with bounded size and strip authorization on archive redirects."""
        url = f"{self.reader._base_url}/repos/{repo}/tarball/{quote(sha, safe='')}"
        headers = await self.reader._headers()
        async with self.reader._client.stream(
            "GET", url, headers=headers, follow_redirects=True
        ) as response:
            if response.is_error:
                raise ProviderError(
                    f"Repository source unavailable (HTTP {response.status_code})",
                    response.status_code,
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_SOURCE:
                    raise SandboxError("Source download exceeds local size limit")
            return bytes(content)

    async def evidence(self, repo: str, sha: str) -> list[dict]:
        """Refresh status and security evidence; lack of permissions is visible."""
        checks = []
        endpoints = [
            (f"commits/{sha}/check-runs", "github:checks", "ci"),
            (f"commits/{sha}/status", "github:status", "ci"),
            ("dependabot/alerts", "github:dependencies", "dependencies"),
            ("code-scanning/alerts", "github:code-scanning", "security"),
            ("secret-scanning/alerts", "github:secrets", "security"),
        ]
        for path, key, area in endpoints:
            try:
                data = await self.request(
                    "GET", repo, path, params={"state": "open", "per_page": 100}
                )
                if isinstance(data, list):
                    status = "fail" if data else "pass"
                    # Never store the secret field or full private advisory response.
                    output = f"{len(data)} open findings (first 100); GitHub security evidence refreshed."
                elif "check_runs" in data:
                    runs = data["check_runs"]
                    failures = [
                        r["name"]
                        for r in runs
                        if r.get("conclusion") in ("failure", "timed_out", "action_required")
                    ]
                    status = (
                        "fail"
                        if failures
                        else (
                            "pass"
                            if runs
                            and all(
                                r.get("conclusion") in ("success", "neutral", "skipped")
                                for r in runs
                            )
                            else "unavailable"
                        )
                    )
                    output = "; ".join(failures) or "GitHub checks: " + status
                else:
                    status = {"success": "pass", "failure": "fail", "error": "fail"}.get(
                        data.get("state"), "unavailable"
                    )
                    output = f"GitHub commit status: {data.get('state', 'missing')}"
                checks.append({"key": key, "area": area, "status": status, "output": output})
            except ProviderError as exc:
                checks.append(
                    {"key": key, "area": area, "status": "unavailable", "output": str(exc)}
                )
        return checks

    async def ref(self, repo: str, branch: str) -> str | None:
        """Get a recorded owned ref; 404 means absent, never permission success."""
        try:
            data = await self.request("GET", repo, f"git/ref/heads/{quote(branch, safe='')}")
            return data["object"]["sha"]
        except ProviderError as exc:
            if exc.status == 404:
                return None
            raise

    async def owned_pr(self, repo: str, branch: str) -> dict | None:
        """Reconcile PR creation using exact head/base ownership, never title matching."""
        owner = repo.split("/")[0]
        prs = await self.request(
            "GET", repo, "pulls", params={"state": "open", "head": f"{owner}:{branch}"}
        )
        matches = [
            p
            for p in prs
            if p["head"]["ref"] == branch
            and p["head"].get("repo", {}).get("full_name", "").lower() == repo.lower()
        ]
        if len(matches) > 1:
            raise ProviderError("Multiple PRs reference the owned branch; reconcile manually")
        return matches[0] if matches else None
