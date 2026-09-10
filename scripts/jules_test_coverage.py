#!/usr/bin/env python3
"""
Jules API Automated Test Coverage & Quality Generator (GitAudit Issue #3)

Dispatches an autonomous coding session to Google Labs Jules API in AUTO_CREATE_PR mode
to inspect untested edge cases and branches in maintainer_api and generate comprehensive
pytest tests to satisfy coverage thresholds.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

JULES_API_BASE = "https://jules.googleapis.com/v1alpha"


def load_env_file(env_path: Path) -> None:
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def build_test_generation_prompt(
    repo: str,
    focus: str | None = None,
    threshold: int = 80,
) -> str:
    focus_guidance = (
        f"Prioritize untested edge cases in: {focus}."
        if focus
        else "Prioritize untested edge cases in maintainer_api/curation.py, maintainer_api/github.py, maintainer_api/reproduction.py, and maintainer_api/activity.py."
    )
    return f"""\
You are working on {repo}.
Task: Audit test coverage and generate pytest unit/integration tests to satisfy >= {threshold}% test coverage.

Context & Objectives:
1. Enforce strict quality and error-handling verification across backend modules.
2. {focus_guidance}
3. Follow existing repository testing conventions:
   - Tests are located in `apps/api/tests/`.
   - Use `pytest-asyncio` with `@pytest.fixture` and in-memory SQLite database sessions.
   - Mock external HTTP/network boundaries without mocking internal application logic unnecessarily.
4. Verify your generated tests by running:
   `make test`
   Ensure all tests pass and test coverage meets or exceeds {threshold}%.
5. Submit a pull request with your tests and concise commit messages.
"""


def create_jules_session(
    api_key: str,
    repo: str,
    starting_branch: str,
    prompt: str,
    auto_pr: bool = True,
    require_approval: bool = False,
) -> dict:
    url = f"{JULES_API_BASE}/sessions"
    owner_repo = repo.strip("/")
    source_uri = f"sources/github/{owner_repo}"

    payload = {
        "prompt": prompt,
        "sourceContext": {
            "source": source_uri,
            "githubRepoContext": {
                "startingBranch": starting_branch,
            },
        },
        "automationMode": "AUTO_CREATE_PR" if auto_pr else "AUTOMATION_MODE_UNSPECIFIED",
        "requirePlanApproval": require_approval,
    }

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "X-Goog-Api-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "GitAudit-CoverageSentinel/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jules API HTTP error {e.code}: {err_msg}") from e
    except URLError as e:
        raise RuntimeError(f"Network error connecting to Jules API: {e.reason}") from e


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trigger Jules API AUTO_CREATE_PR session for automated test generation."
    )
    parser.add_argument(
        "--repo",
        default="HazemHassine/GitAudit",
        help="Target GitHub repository (owner/repo). Default: HazemHassine/GitAudit",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Base starting branch. Default: main",
    )
    parser.add_argument(
        "--focus",
        help="Specific module or area to focus test generation on (e.g. curation, reproduction, github)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=80,
        help="Target coverage threshold percentage. Default: 80",
    )
    parser.add_argument(
        "--no-auto-pr",
        action="store_true",
        help="Disable automatic PR creation mode",
    )
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require manual plan approval before Jules applies diffs",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually submit session to live Jules API (default is dry-run to conserve quota)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompt and API payload without sending request",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    load_env_file(repo_root / ".env")

    api_key = os.environ.get("JULES_API_KEY", "").strip()

    prompt = build_test_generation_prompt(
        repo=args.repo,
        focus=args.focus,
        threshold=args.threshold,
    )

    # Dry-run by default unless --live is specified, protecting user quota
    is_dry_run = args.dry_run or not args.live

    if is_dry_run:
        print("[DRY RUN MODE - Jules API quota preserved]")
        print("Target Repo:", args.repo)
        print("Branch:", args.branch)
        print("Target Coverage Threshold:", f"{args.threshold}%")
        print("Automation Mode:", "AUTO_CREATE_PR" if not args.no_auto_pr else "UNSPECIFIED")
        print("-" * 60)
        print("Generated Prompt for Jules:\n")
        print(prompt)
        print("-" * 60)
        print("Dry run completed successfully. (Use --live to dispatch to live Jules API)")
        return 0

    if not api_key:
        print("Error: JULES_API_KEY not found in environment or .env file.", file=sys.stderr)
        return 1

    print(f"Submitting Jules Test Generation session for {args.repo} ({args.branch})...")
    try:
        session = create_jules_session(
            api_key=api_key,
            repo=args.repo,
            starting_branch=args.branch,
            prompt=prompt,
            auto_pr=not args.no_auto_pr,
            require_approval=args.require_approval,
        )
        print("✓ Jules test-generation session successfully created!")
        print(f"  Session ID: {session.get('name', 'N/A')}")
        print(f"  Web Console: https://jules.google.com")
        return 0
    except Exception as exc:
        print(f"Failed to create Jules session: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
