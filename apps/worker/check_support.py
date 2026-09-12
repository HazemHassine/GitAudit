"""Offline documentation links and existing coverage reports; no imposed project rules."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

SKIP = {"node_modules", ".git", ".venv", ".audit-venv", "dist", "vendor"}


def paths(root):
    """Enumerate bounded repository files excluding generated dependency directories."""
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and not SKIP.intersection(p.relative_to(root).parts)
    ]


def links(root):
    """Check relative Markdown file links; explicitly leave external URLs unavailable."""
    failures, checked, external = [], 0, 0
    for file in paths(root):
        if file.suffix.lower() != ".md" or file.stat().st_size > 2_000_000:
            continue
        for target in re.findall(
            r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", file.read_text(errors="replace")
        ):
            url = urlparse(target.strip("<>"))
            if url.scheme or url.netloc:
                external += 1
                continue
            if not url.path or url.path.startswith("/"):
                continue
            checked += 1
            destination = file.parent / unquote(url.path)
            if not destination.exists():
                failures.append(f"{file.relative_to(root)}: missing {url.path}")
    print(
        f"Checked {checked} relative file links. External URL/anchor validation unavailable offline ({external} external links)."
    )
    print("\n".join(failures))
    return bool(failures)


def coverage(root):
    """Read reports already produced by the repository; no fixed coverage target."""
    metrics = {}
    for file in paths(root):
        if file.stat().st_size > 2_000_000:
            continue
        if file.name == "coverage.xml":
            document = ET.fromstring(file.read_text())
            value = document.get("line-rate")
            if value is not None:
                metrics[str(file.relative_to(root))] = float(value) * 100
        elif file.name == "coverage-summary.json":
            document = json.loads(file.read_text())
            value = document.get("total", {}).get("lines", {}).get("pct")
            if isinstance(value, (int, float)):
                metrics[str(file.relative_to(root))] = value
    print(
        json.dumps(
            {
                "coverage_percent": metrics,
                "note": "Existing reports only; repository thresholds apply.",
            }
        )
    )
    return 0 if metrics else 3


if __name__ == "__main__":
    if sys.argv[1] == "version":
        print("GitAudit offline evidence helper 1")
    else:
        raise SystemExit(
            int({"links": links, "coverage": coverage}[sys.argv[1]](Path.cwd()))
        )
