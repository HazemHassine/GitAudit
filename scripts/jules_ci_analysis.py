#!/usr/bin/env python3
"""Jules CI Analysis CLI

Dispatches an autonomous CI pipeline analysis session to Google Labs Jules API.
Analyzes GitHub Actions workflows for bottlenecks, flakiness, and parallelization.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

JULES_API_BASE_URL = "https://jules.googleapis.com/v1alpha"


def load_env_file(env_path: Path) -> None:
    """Load key-value pairs from a local .env file if present."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def get_latest_ci_log() -> str | None:
    """Attempt to fetch the latest failed CI run log using the GitHub CLI (gh)."""
    try:
        # Check if gh is installed and authenticated
        res = subprocess.run(
            ["gh", "run", "list", "--workflow=CI", "--limit=1", "--json", "conclusion,databaseId"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout)
        if not data:
            return None
        run_id = data[0].get("databaseId")
        if not run_id:
            return None

        # Fetch failed log snippet
        log_res = subprocess.run(
            ["gh", "run", "view", str(run_id), "--log-failed"],
            capture_output=True,
            text=True,
            check=False,
        )
        if log_res.returncode == 0 and log_res.stdout.strip():
            # Truncate to reasonable length for prompt
            lines = log_res.stdout.splitlines()[-100:]
            return "\n".join(lines)
    except Exception:
        return None
    return None


def build_prompt(focus: str, ci_log: str | None = None) -> str:
    prompt_parts = [
        "You are an autonomous CI optimization and reliability engineer for GitAudit.",
        "",
        "Please analyze our GitHub Actions CI setup in `.github/workflows/ci.yml` and `Makefile`.",
        f"Primary focus areas: {focus}.",
        "",
        "Specific objectives:",
        "1. Bottleneck Analysis: Identify slow sequential steps (e.g. monolithic jobs,",
        "   redundant installs, uncached dependencies, browser download steps).",
        "2. Flakiness & Reliability: Ensure database service health checks and migrations",
        "   have deterministic wait times without brittle timeouts.",
        "3. Parallelization: Propose splitting the monolithic `test` job into concurrent jobs:",
        "   - backend: Pytest, Ruff, Actionlint, Migrations",
        "   - frontend: ESLint, TypeScript check, Next.js build",
        "   - e2e: Playwright browser tests",
        "   - container: Docker compose build check",
        "4. Pull Request: Produce clean, working workflow updates that preserve all existing checks.",
    ]

    if ci_log:
        prompt_parts.extend([
            "",
            "Recent CI failure output for context:",
            "```",
            ci_log,
            "```",
        ])

    return "\n".join(prompt_parts)


def create_jules_session(
    api_key: str,
    repo: str,
    starting_branch: str,
    prompt: str,
    auto_pr: bool = True,
    require_approval: bool = False,
) -> dict[str, Any]:
    """Dispatch a new session to the Jules API."""
    url = f"{JULES_API_BASE_URL}/sessions"
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "prompt": prompt,
        "sourceContext": {
            "source": f"sources/github/{repo}",
            "githubRepoContext": {
                "startingBranch": starting_branch,
            },
        },
        "requirePlanApproval": require_approval,
    }

    if auto_pr:
        payload["automationMode"] = "AUTO_CREATE_PR"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def main() -> int:
    # Auto-load .env
    repo_root = Path(__file__).resolve().parent.parent
    load_env_file(repo_root / ".env")

    parser = argparse.ArgumentParser(
        description="Trigger Jules AI session for CI pipeline audit and optimization."
    )
    parser.add_argument(
        "--repo",
        default="HazemHassine/GitAudit",
        help="Target GitHub repository (owner/repo). Default: HazemHassine/GitAudit",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Starting git branch for Jules. Default: main",
    )
    parser.add_argument(
        "--focus",
        default="bottlenecks, flakiness, parallelization",
        help="Audit focus areas. Default: 'bottlenecks, flakiness, parallelization'",
    )
    parser.add_argument(
        "--no-auto-pr",
        dest="auto_pr",
        action="store_false",
        help="Disable automatic pull request generation.",
    )
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require explicit plan approval before Jules executes changes.",
    )
    parser.add_argument(
        "--include-ci-log",
        action="store_true",
        help="Include the latest failed CI log in the prompt via gh CLI.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the constructed payload and prompt without calling the API.",
    )

    args = parser.parse_args()

    api_key = os.environ.get("JULES_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print(
            "Error: JULES_API_KEY is not set. Set it in your environment or .env file.",
            file=sys.stderr,
        )
        return 1

    ci_log = get_latest_ci_log() if args.include_ci_log else None
    prompt = build_prompt(args.focus, ci_log)

    payload = {
        "prompt": prompt,
        "sourceContext": {
            "source": f"sources/github/{args.repo}",
            "githubRepoContext": {
                "startingBranch": args.branch,
            },
        },
        "requirePlanApproval": args.require_approval,
        "automationMode": "AUTO_CREATE_PR" if args.auto_pr else "DEFAULT",
    }

    if args.dry_run:
        print("[Dry Run] Jules API Session Payload:")
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Submitting Jules CI Analysis session for {args.repo} ({args.branch})...")
    try:
        result = create_jules_session(
            api_key=api_key,
            repo=args.repo,
            starting_branch=args.branch,
            prompt=prompt,
            auto_pr=args.auto_pr,
            require_approval=args.require_approval,
        )
        session_id = result.get("name", "unknown")
        print("✓ Jules session successfully created!")
        print(f"  Session: {session_id}")
        print(f"  Web Console: https://jules.google.com")
        return 0
    except httpx.HTTPStatusError as exc:
        print(f"API Error ({exc.response.status_code}): {exc.response.text}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to create Jules session: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
