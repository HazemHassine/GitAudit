"""Credential-free Docker execution and bounded, non-shell trusted commands."""

import asyncio
import io
import os
import re
import tarfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .config import Settings

MAX_OUTPUT = 128_000
MAX_SOURCE = 200_000_000


class SandboxError(RuntimeError):
    """Execution cannot proceed within the configured isolation boundary."""


async def command(
    *argv: str, cwd: Path | None = None, timeout: int = 60, stdin: bytes | None = None
) -> tuple[int, str]:
    """Run trusted argv with a scrubbed environment, deadline and bounded output."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C.UTF-8",
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise SandboxError(
            f"Required executable unavailable: {argv[0]}; host fallback disabled"
        ) from exc
    output = bytearray()

    async def drain() -> None:
        if stdin and proc.stdin:
            proc.stdin.write(stdin)
            await proc.stdin.drain()
            proc.stdin.close()
        while chunk := await proc.stdout.read(8192):
            if len(output) < MAX_OUTPUT:
                output.extend(chunk[: MAX_OUTPUT - len(output)])
        await proc.wait()

    try:
        await asyncio.wait_for(drain(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    return proc.returncode or 0, output.decode(errors="replace")


def extract_source(archive: bytes, destination: Path) -> None:
    """Extract GitHub tarballs without links, devices, traversal or oversized files."""
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts:
                raise SandboxError("Unsafe source archive path")
            relative = Path(*parts[1:])
            if ".git" in relative.parts:
                raise SandboxError("Source archive contains Git metadata")
            if member.isdir():
                (destination / relative).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise SandboxError("Source archive contains unsupported links or devices")
            total += member.size
            if total > MAX_SOURCE or member.size > 20_000_000:
                raise SandboxError("Repository exceeds local source size limit")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


class DockerWorkspace:
    """Disposable named volume, with no credentials, host mounts or Docker socket."""

    def __init__(self, settings: Settings, identity: str):
        self.settings = settings
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", identity):
            raise ValueError("Invalid sandbox identity")
        self.identity = f"gitaudit-{identity}"
        self.volume = f"{self.identity}-source"
        self.containers: set[str] = set()
        self.image_id = settings.audit_image

    async def prepare(self, source: Path) -> None:
        """Copy source into a Docker volume; never run repository code on the host."""
        code, output = await command("docker", "info", "--format", "{{.ServerVersion}}")
        if code:
            raise SandboxError("Docker unavailable; host fallback disabled")
        code, output = await command(
            "docker", "image", "inspect", self.settings.audit_image, "--format", "{{.Id}}"
        )
        if code:
            raise SandboxError("Check image unavailable; build the checks image first")
        self.image_id = output.strip()
        await self.cleanup()
        code, _ = await command(
            "docker",
            "volume",
            "create",
            "--label",
            f"gitaudit.identity={self.identity}",
            self.volume,
        )
        if code:
            raise SandboxError("Cannot create Docker workspace")
        name = f"{self.identity}-copy"
        self.containers.add(name)
        try:
            code, out = await command(
                "docker",
                "create",
                "--name",
                name,
                "--network=none",
                "--label",
                f"gitaudit.identity={self.identity}",
                "--mount",
                f"type=volume,src={self.volume},dst=/workspace",
                self.image_id,
                "true",
            )
            if code:
                raise SandboxError(out)
            code, out = await command("docker", "cp", f"{source}/.", f"{name}:/workspace")
            if code:
                raise SandboxError(out)
        finally:
            await command("docker", "rm", "-f", name)
            self.containers.discard(name)

    async def run(
        self, argv: list[str], directory: str = ".", network: bool = False
    ) -> tuple[int, str]:
        """Run one check with restricted network, resource limits and forced cleanup."""
        if PurePosixPath(directory).is_absolute() or ".." in PurePosixPath(directory).parts:
            raise SandboxError("Invalid check directory")
        name = f"{self.identity}-{uuid4().hex[:10]}"
        self.containers.add(name)
        options = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            f"gitaudit.identity={self.identity}",
            "--memory=2g",
            "--memory-swap=2g",
            "--cpus=2",
            "--pids-limit=256",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
            "--user",
            "0:0",
            "--mount",
            f"type=volume,src={self.volume},dst=/workspace",
            "--workdir",
            f"/workspace/{directory}",
            "--env",
            "HOME=/tmp",
            "--env",
            "CI=true",
            "--env",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--network",
            self.settings.audit_install_network if network else "none",
        ]
        if network:
            # The internal network only reaches the allowlisting dependency proxy.
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                options.extend(["--env", f"{key}={self.settings.audit_install_proxy}"])
        try:
            return await command(
                *options, self.image_id, *argv, timeout=self.settings.audit_timeout_seconds
            )
        except TimeoutError:
            return (
                124,
                "Deadline exceeded; container removed. Network exceptions require configuration.",
            )
        finally:
            await command("docker", "rm", "-f", name)
            self.containers.discard(name)

    async def cleanup(self) -> None:
        """Remove all resources for this attempt, including those left after a crash."""
        code, out = await command(
            "docker", "ps", "-aq", "--filter", f"label=gitaudit.identity={self.identity}"
        )
        if code:
            raise SandboxError("Cannot reconcile Docker containers")
        for name in out.split():
            await command("docker", "rm", "-f", name)
        await command("docker", "volume", "rm", "-f", self.volume)
