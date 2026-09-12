"""Manifest-driven Python/Node checks with explicit coverage and evidence gaps."""

import hashlib
import json
import re
import shlex
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .sandbox import DockerWorkspace

ADAPTER_VERSION = "1"
AREAS = (
    "build",
    "tests",
    "ci",
    "dependencies",
    "security",
    "deployment",
    "documentation",
    "maintenance",
)
SKIP_DIRS = {"node_modules", ".git", ".venv", "vendor", "dist", "build"}


@dataclass
class Check:
    """A repository-owned command and the environment required to execute it."""

    key: str
    area: str
    directory: str
    argv: list[str]
    version: list[str]
    network: bool = False
    installation: bool = False
    requires_install: bool = False


def digest(value: object) -> str:
    """Stable content key used for caches, requests and plan versions."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def discover(root: Path) -> list[Check]:
    """Discover workspace manifests and existing rules without imposing thresholds."""
    checks: list[Check] = []
    manifests = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS)
    )
    if len(manifests) > 20_000:
        raise ValueError("Repository exceeds supported file count")
    node_roots = []
    for file in manifests:
        if file.name != "package.json":
            continue
        data = json.loads(file.read_text())
        directory = file.parent.relative_to(root).as_posix()
        # npm workspaces share the root lockfile/install; independent packages install separately.
        parent_workspace = next(
            (p for p, d in node_roots if d.get("workspaces") and file.parent.is_relative_to(p)),
            None,
        )
        if not parent_workspace:
            node_roots.append((file.parent, data))
            manager = str(data.get("packageManager", "npm")).split("@")[0]
            lock = file.parent / "package-lock.json"
            if manager == "npm" and lock.exists():
                checks.append(
                    Check(
                        f"{directory}:install",
                        "dependencies",
                        directory,
                        ["npm", "ci", "--no-audit", "--no-fund"],
                        ["npm", "--version"],
                        network=True,
                        installation=True,
                    )
                )
                checks.append(
                    Check(
                        f"{directory}:npm-audit",
                        "dependencies",
                        directory,
                        ["npm", "audit", "--package-lock-only", "--json"],
                        ["npm", "--version"],
                        network=True,
                    )
                )
            elif manager in ("pnpm", "yarn"):
                lockname = "pnpm-lock.yaml" if manager == "pnpm" else "yarn.lock"
                if (file.parent / lockname).exists():
                    checks.append(
                        Check(
                            f"{directory}:install",
                            "dependencies",
                            directory,
                            [manager, "install", "--frozen-lockfile"],
                            [manager, "--version"],
                            network=True,
                            installation=True,
                        )
                    )
        for script, area in (
            ("build", "build"),
            ("typecheck", "build"),
            ("test", "tests"),
            ("lint", "maintenance"),
            ("format:check", "maintenance"),
            ("docs:check", "documentation"),
            ("test:contract", "documentation"),
        ):
            if script in data.get("scripts", {}):
                checks.append(
                    Check(
                        f"{directory}:{script}",
                        area,
                        directory,
                        ["npm", "run", script],
                        ["node", "--version"],
                        requires_install=True,
                    )
                )
    for file in manifests:
        if file.name != "pyproject.toml" and not (
            file.name == "requirements.txt" and not (file.parent / "pyproject.toml").exists()
        ):
            continue
        directory = file.parent.relative_to(root).as_posix()
        data = tomllib.loads(file.read_text()) if file.suffix == ".toml" else {}
        tool = data.get("tool", {})
        prefix = f"/workspace/{directory}/.audit-venv/bin"
        quoted_prefix = shlex.quote(prefix)
        if (file.parent / "uv.lock").exists():
            install = ["uv", "sync", "--frozen", "--all-extras"]
            prefix = f"/workspace/{directory}/.venv/bin"
        elif file.name == "requirements.txt":
            install = [
                "sh",
                "-c",
                f"python -m venv .audit-venv && {quoted_prefix}/pip install -r requirements.txt",
            ]
        else:
            extras = data.get("project", {}).get("optional-dependencies", {})
            selected = [name for name in ("dev", "test", "tests") if name in extras]
            spec = ".[" + ",".join(selected) + "]" if selected else "."
            install = [
                "sh",
                "-c",
                f"python -m venv .audit-venv && {quoted_prefix}/pip install {shlex.quote(spec)}",
            ]
        checks.append(
            Check(
                f"{directory}:install",
                "dependencies",
                directory,
                install,
                ["python", "--version"],
                network=True,
                installation=True,
            )
        )
        if (
            "pytest" in tool
            or (file.parent / "pytest.ini").exists()
            or (file.parent / "tests").is_dir()
        ):
            checks.append(
                Check(
                    f"{directory}:pytest",
                    "tests",
                    directory,
                    [f"{prefix}/python", "-m", "pytest"],
                    ["python", "--version"],
                    requires_install=True,
                )
            )
        if "ruff" in tool or any((file.parent / p).exists() for p in ("ruff.toml", ".ruff.toml")):
            checks.append(
                Check(
                    f"{directory}:ruff",
                    "maintenance",
                    directory,
                    ["ruff", "check", "."],
                    ["ruff", "--version"],
                )
            )
        if "mypy" in tool:
            checks.append(
                Check(
                    f"{directory}:mypy",
                    "build",
                    directory,
                    [f"{prefix}/python", "-m", "mypy", "."],
                    ["python", "--version"],
                    requires_install=True,
                )
            )
        if "build-system" in data:
            checks.append(
                Check(
                    f"{directory}:build",
                    "build",
                    directory,
                    ["uv", "build", "--no-build-isolation", "--python", f"{prefix}/python"],
                    ["uv", "--version"],
                    requires_install=True,
                )
            )
        # Audit the installed, resolved dependency set; lockfile/frozen install is used when available.
        checks.append(
            Check(
                f"{directory}:pip-audit",
                "dependencies",
                directory,
                ["pip-audit", "--path", f"{prefix}/../lib/python3.12/site-packages", "-f", "json"],
                ["pip-audit", "--version"],
                network=True,
                requires_install=True,
            )
        )
    if any(
        p.suffix in (".yml", ".yaml") and ".github/workflows" in p.as_posix() for p in manifests
    ):
        checks.append(
            Check(
                "actionlint", "ci", ".", ["actionlint", "-shellcheck="], ["actionlint", "-version"]
            )
        )
    checks.append(
        Check(
            "gitleaks",
            "security",
            ".",
            ["gitleaks", "dir", ".", "--redact", "--no-banner"],
            ["gitleaks", "version"],
        )
    )
    for file in manifests:
        relative = file.relative_to(root).as_posix()
        if file.name == "Dockerfile" or file.name.endswith(".Dockerfile"):
            checks.append(
                Check(
                    relative, "deployment", ".", ["hadolint", relative], ["hadolint", "--version"]
                )
            )
        if file.name in (
            "compose.yaml",
            "compose.yml",
            "docker-compose.yml",
            "docker-compose.yaml",
        ):
            checks.append(
                Check(
                    relative,
                    "deployment",
                    ".",
                    [
                        "docker",
                        "compose",
                        "-f",
                        relative,
                        "config",
                        "--quiet",
                        "--no-env-resolution",
                    ],
                    ["docker", "compose", "version"],
                )
            )
    if any(p.suffix == ".tf" for p in manifests):
        checks.append(
            Check(
                "terraform",
                "deployment",
                ".",
                ["terraform", "fmt", "-check", "-recursive"],
                ["terraform", "version"],
            )
        )
    if any(p.suffix == ".md" for p in manifests):
        checks.append(
            Check(
                "doc-links",
                "documentation",
                ".",
                ["python", "/opt/gitaudit/check_support.py", "links"],
                ["python", "/opt/gitaudit/check_support.py", "version"],
            )
        )
    checks.append(
        Check(
            "coverage-reports",
            "tests",
            ".",
            ["python", "/opt/gitaudit/check_support.py", "coverage"],
            ["python", "/opt/gitaudit/check_support.py", "version"],
        )
    )
    return checks


def result(check: Check, status: str, output: str, version: str, sha: str) -> dict:
    """Attach provenance to deterministic outcomes, including unavailable checks."""
    return {
        **asdict(check),
        "status": status,
        "output": output[-128_000:],
        "tool_version": version.strip(),
        "commit": sha,
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cached": False,
    }


async def execute_checks(
    workspace: DockerWorkspace,
    checks: list[Check],
    sha: str,
    emit,
    cached: list[dict] | None = None,
) -> list[dict]:
    """Run applicable commands; installation failures never become test passes."""
    results = []
    failed_installs: set[str] = set()
    installed = {check.directory for check in checks if check.installation}
    cache = {item["key"]: item for item in (cached or [])}
    for check in checks:
        await emit(
            f"{check.key}: {'installing dependencies' if check.installation else 'checking repository'}"
        )
        if check.key in cache and not check.network:
            results.append({**cache[check.key], "cached": True})
            continue
        related_install = any(
            check.directory == p or p == "." or check.directory.startswith(p + "/")
            for p in installed
        )
        failed = any(
            check.directory == p or p == "." or check.directory.startswith(p + "/")
            for p in failed_installs
        )
        if check.requires_install and (failed or not related_install):
            results.append(
                result(
                    check,
                    "installation_failed" if failed else "missing_configuration",
                    "Dependency installation failed"
                    if failed
                    else "No supported lockfile/install configuration",
                    "unavailable",
                    sha,
                )
            )
            continue
        code, version = await workspace.run(check.version, check.directory)
        if code:
            results.append(
                result(
                    check,
                    "unavailable",
                    "Required tool is unavailable: " + version,
                    "unavailable",
                    sha,
                )
            )
            if check.installation:
                failed_installs.add(check.directory)
            continue
        started = datetime.now(UTC).isoformat()
        code, output = await workspace.run(check.argv, check.directory, check.network)
        status = "pass" if code == 0 else "fail"
        if check.key == "coverage-reports" and code == 3:
            status = "missing_configuration"
        if code in (125, 126, 127):
            status = "unavailable"
        elif code == 124:
            status = "blocked"
        elif code and check.installation:
            status = "installation_failed"
        if check.installation and code:
            failed_installs.add(check.directory)
        item = result(check, status, output, version, sha)
        item.update(started_at=started, exit_code=code)
        if check.key == "coverage-reports" and code == 0:
            try:
                item["metrics"] = json.loads(output)
            except ValueError:
                item["status"] = "unavailable"
        elif check.area == "tests":
            counts = re.findall(r"(\d+) passed", output)
            if counts:
                item["metrics"] = {"tests_passed": int(counts[-1])}
        results.append(item)
    for area in AREAS:
        if not any(c.area == area for c in checks):
            missing = Check(f"missing:{area}", area, ".", [], [])
            results.append(
                result(
                    missing,
                    "unsupported" if not installed else "missing_configuration",
                    "No supported repository rule detected",
                    ADAPTER_VERSION,
                    sha,
                )
            )
    return results


def findings_for(checks: list[dict]) -> list[dict]:
    """Prioritize evidenced failures; unavailable coverage is never an AI task by default."""
    priority = {"security": 0, "dependencies": 1, "build": 2, "tests": 2}
    return sorted(
        [
            {
                "key": c["key"],
                "area": c["area"],
                "priority": priority.get(c["area"], 5),
                "evidence": c["output"],
                "directory": c.get("directory", "."),
                "required_validation": c.get("argv", []),
            }
            for c in checks
            if c["status"] == "fail"
        ],
        key=lambda c: c["priority"],
    )


def validation_passes(before: list[dict], after: list[dict]) -> bool:
    """Require measured checks, no lost successes and improvement in an evidenced failure."""
    old = {c["key"]: c for c in before}
    new = {c["key"]: c for c in after}
    if not any(
        c["status"] == "pass" and c.get("area") in ("tests", "build", "maintenance") for c in after
    ):
        return False
    if any(
        c["status"] == "pass" and new.get(key, {}).get("status") != "pass" for key, c in old.items()
    ):
        return False
    if any(
        c["status"] == "fail" and old.get(key, {}).get("status") != "fail" for key, c in new.items()
    ):
        return False
    for key, previous in old.items():
        old_metrics = previous.get("metrics", {})
        new_metrics = new.get(key, {}).get("metrics", {})
        if (
            "tests_passed" in old_metrics
            and new_metrics.get("tests_passed", -1) < old_metrics["tests_passed"]
        ):
            return False
        for report, value in old_metrics.get("coverage_percent", {}).items():
            if new_metrics.get("coverage_percent", {}).get(report, -1) < value:
                return False
    failed = [key for key, c in old.items() if c["status"] == "fail"]
    return not failed or any(new.get(key, {}).get("status") == "pass" for key in failed)
