#!/usr/bin/env python3
"""Preview a review or queue it through the local, budget-enforcing audit backend."""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))
prompts = importlib.import_module("maintainer_api.jules_prompts")


def main() -> int:
    """Require explicit live dispatch and a reusable request key for CLI retries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--area", choices=sorted(prompts.JULES_AUDIT_DEFINITIONS), default="build"
    )
    parser.add_argument("--focus", default="")
    parser.add_argument("--repository-id", help="Connected repository UUID")
    parser.add_argument(
        "--idempotency-key", help="Stable key; reuse when retrying this request"
    )
    parser.add_argument(
        "--api-url", default=os.environ.get("GITAUDIT_API_URL", "http://localhost:8001")
    )
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("[PREVIEW] No Jules session created.")
        print(prompts.build_jules_prompt(args.area, args.focus))
        return 0
    password = os.environ.get("GITAUDIT_OWNER_PASSWORD", "")
    if not args.repository_id or not args.idempotency_key or not password:
        parser.error(
            "--live requires --repository-id, --idempotency-key and GITAUDIT_OWNER_PASSWORD"
        )
    parsed = urlparse(args.api_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        parser.error("Use HTTPS or a loopback HTTP backend")
    payload = {
        "repository_ids": [args.repository_id],
        "deep_review": True,
        "force": False,
    }
    request = Request(
        args.api_url.rstrip("/") + "/api/v1/audits/runs",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {password}",
            "Content-Type": "application/json",
            "Idempotency-Key": args.idempotency_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310 - explicit HTTPS/loopback backend
            run = json.load(response)
    except HTTPError as exc:
        print(f"Audit backend rejected the request (HTTP {exc.code})", file=sys.stderr)
        return 1
    except (URLError, OSError, ValueError):
        print(
            "Backend response unavailable. Retry with the same idempotency key.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Audit queued: {run['id']}. Review and approve its plan in /audits/runs/{run['id']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
