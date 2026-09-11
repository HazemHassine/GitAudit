#!/usr/bin/env python3
"""Prepare or dispatch a Jules review for one GitAudit audit area.

This command shares its prompts with the API. It previews by default; ``--live``
is required to make a network request and Jules still requires plan approval
before it can make changes.
"""

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "api" / "src"))

_prompts = importlib.import_module("maintainer_api.jules_prompts")
JULES_AUDIT_DEFINITIONS = _prompts.JULES_AUDIT_DEFINITIONS
build_jules_prompt = _prompts.build_jules_prompt


JULES_API_URL = "https://jules.googleapis.com/v1alpha/sessions"
SESSION_NAME = re.compile(r"sessions/[A-Za-z0-9_-]+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a shared Jules audit review.")
    parser.add_argument("--area", choices=sorted(JULES_AUDIT_DEFINITIONS), required=True)
    parser.add_argument("--focus", default="", help="Optional scoped review request.")
    parser.add_argument(
        "--repo",
        default=os.environ.get("JULES_SOURCE_REPOSITORY", "HazemHassine/GitAudit"),
        help="GitHub owner/repository used as the Jules source context.",
    )
    parser.add_argument(
        "--branch",
        default=os.environ.get("JULES_STARTING_BRANCH", "main"),
        help="Starting branch for the review.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Submit the review to Jules. The default only prints a preview.",
    )
    return parser.parse_args()


def payload_for(args: argparse.Namespace) -> dict[str, object]:
    return {
        "prompt": build_jules_prompt(args.area, args.focus),
        "sourceContext": {
            "source": f"sources/github/{args.repo}",
            "githubRepoContext": {"startingBranch": args.branch},
        },
        "automationMode": "AUTO_CREATE_PR",
        "requirePlanApproval": True,
    }


def create_session(payload: dict[str, object], api_key: str) -> str:
    request = Request(
        JULES_API_URL,
        data=json.dumps(payload).encode(),
        headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310 - fixed HTTPS endpoint
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        raise RuntimeError(f"Jules API rejected the request (HTTP {exc.code}).") from exc
    except (URLError, OSError, ValueError) as exc:
        raise RuntimeError("Jules API request failed.") from exc

    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(name, str) or not SESSION_NAME.fullmatch(name):
        raise RuntimeError("Jules API returned no valid session name.")
    return name


def main() -> int:
    args = parse_args()
    payload = payload_for(args)
    if not args.live:
        print("[PREVIEW] Jules was not called. Review payload:")
        print(json.dumps(payload, indent=2))
        return 0

    api_key = os.environ.get("JULES_API_KEY", "").strip()
    if not api_key:
        print("JULES_API_KEY is required for --live.", file=sys.stderr)
        return 2

    try:
        name = create_session(payload, api_key)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    session_id = name.split("/", maxsplit=1)[1]
    print(f"Jules session created: {name}")
    print(f"Review its plan before approving changes: https://jules.google.com/session/{session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
