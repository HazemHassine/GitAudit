"""Independent patch validation and journaled publication to one owned PR."""

import base64
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from .audit_checks import Check, discover, execute_checks, validation_passes
from .audit_providers import ProviderError
from .audit_service import event, now
from .database import AuditPRRecord
from .sandbox import SandboxError, command, extract_source


async def git(root: Path, *args: str, stdin: bytes | None = None) -> str:
    """Run trusted Git operations with hooks and global configuration disabled."""
    code, output = await command(
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "user.name=GitAudit",
        "-c",
        "user.email=gitaudit@localhost",
        *args,
        cwd=root,
        stdin=stdin,
    )
    if code:
        raise SandboxError(f"Patch conflict or Git validation failure: {output}")
    return output.strip()


def files(root: Path) -> dict[str, tuple[bytes, str]]:
    """Read source trees without Git metadata, symlinks or special files."""
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if path.is_symlink():
            raise SandboxError("Patch introduces an unsupported symbolic link")
        if path.is_file():
            if path.stat().st_size > 20_000_000:
                raise SandboxError("Patch file exceeds publication size limit")
            result[relative.as_posix()] = (
                path.read_bytes(),
                "100755" if path.stat().st_mode & 0o111 else "100644",
            )
    return result


async def apply_patch(
    root: Path,
    base_archive: bytes,
    target_archive: bytes,
    patch: dict,
    source: str,
    base_sha: str,
    findings: list[dict],
    deep_review: bool,
    allow_workflows: bool,
) -> tuple[dict, dict]:
    """Verify provenance, merge onto the publication base and enforce permitted file scope."""
    artifact = patch.get("gitPatch", {})
    if patch.get("source") != source or artifact.get("baseCommitId") != base_sha:
        raise SandboxError("Patch source or base commit does not match the audited repository")
    diff = artifact.get("unidiffPatch", "")
    if not diff.strip() or len(diff) > 20_000_000:
        raise SandboxError("Empty or oversized patch cannot be published")
    extract_source(base_archive, root)
    await git(root, "init", "-q")
    await git(root, "add", "--all")
    await git(root, "commit", "-qm", "Recorded audit base", "--allow-empty")
    # Keep the original blobs in Git for a real three-way patch application.
    for child in root.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    extract_source(target_archive, root)
    before = files(root)
    await git(root, "add", "--all")
    await git(root, "commit", "-qm", "Current publication base", "--allow-empty")
    await git(root, "apply", "--3way", "--index", "--whitespace=error", "-", stdin=diff.encode())
    after = files(root)
    changed = [name for name in set(before) | set(after) if before.get(name) != after.get(name)]
    if not changed:
        raise SandboxError("Patch is empty on the current publication base")
    directories = [f.get("directory", ".") for f in findings]
    for name in changed:
        parts = Path(name).parts
        if ".git" in parts or name.startswith(".env") or name.endswith((".pem", ".key")):
            raise SandboxError(f"Patch touches a protected path: {name}")
        if name.startswith(".github/workflows/") and not allow_workflows:
            raise SandboxError("Workflow edits require configured workflow write permission")
        if (
            not deep_review
            and not any(p == "." or name.startswith(p.rstrip("/") + "/") for p in directories)
            and not name.startswith(("tests/", "docs/"))
        ):
            raise SandboxError(f"Patch is outside the evidenced repair scope: {name}")
        if name not in after and (
            "test" in name.lower() or Path(name).name in ("pyproject.toml", "package.json")
        ):
            raise SandboxError(f"Removing test/configuration files requires attention: {name}")
    return before, after


def pr_body(worker, run, repository: str) -> str:
    """Describe actual findings and before/after results, including remaining limits."""
    after = {c["key"]: c for c in run.validation}
    addressed = [f["key"] for f in run.findings if after.get(f["key"], {}).get("status") == "pass"]
    deferred = [f["key"] for f in run.findings if f["key"] not in addressed]
    limitations = [f"{c['key']}: {c['status']}" for c in run.validation if c["status"] != "pass"]
    purposes = sorted({f["area"] for f in run.findings}) or ["Requested deep review"]
    comparison = [
        f"| {c['key']} | {c['status']} | {after.get(c['key'], {}).get('status', 'unavailable')} |"
        for c in run.checks
    ]
    return (
        f"Repository checks for **{repository}** at `{run.base_sha}`.\n\n"
        f"Changes by purpose: {', '.join(purposes)}.\n\n"
        f"Findings addressed: {', '.join(addressed) or 'Requested review changes'}.\n\n"
        f"Findings deferred: {', '.join(deferred) or 'None'}.\n\n"
        "| Check | Before | After |\n| --- | --- | --- |\n"
        + "\n".join(comparison)
        + "\n\nRemaining limitations / unchanged baseline failures:\n"
        + "\n".join(f"- {item}" for item in limitations or ["None measured"])
        + f"\n\n[Run report]({worker.settings.public_web_url}/audits/runs/{run.batch_id}) · "
        f"[Jules session](https://jules.google.com/session/{run.session_name.split('/')[-1]})\n\n"
        "Validated independently by GitAudit. Review and merge remain the owner's action.\n"
    )


async def validate_and_publish(worker, job_id, token, repository: str) -> None:
    """Rebase if necessary, validate in Docker, then journal each externally visible write."""
    async with worker.factory() as session:
        control, _, run, batch = await worker.locked(session, job_id, token)
        if (
            batch.stopped
            or control.paused
            or run.approved_version != run.plan_version
            or not run.approved_version
        ):
            return
        association = await session.get(AuditPRRecord, run.repository_id)
        if association is None:
            association = AuditPRRecord(
                repository_id=run.repository_id,
                branch=f"gitaudit/repository-check-{run.repository_id.hex[:12]}",
            )
            session.add(association)
            await session.flush()
        if association.pending:
            await publish_pending(worker, session, run, batch, association, repository)
            await session.commit()
            return
        if association.number:
            pr = await worker.github.request("GET", repository, f"pulls/{association.number}")
            if pr["state"] != "open":
                association.branch = f"gitaudit/repository-check-{run.id.hex[:12]}"
                association.number, association.url, association.head_sha = None, None, None
        ref = await worker.github.ref(repository, association.branch)
        if ref != association.head_sha:
            raise SandboxError(
                "Owned branch changed outside GitAudit; human commits are preserved and require attention"
            )
        default_branch, current_sha = await worker.github.head(repository)
        target_sha = ref or current_sha
        # Reconcile a moved default branch with an existing PR through GitHub's merge-base evidence.
        # A merge is needed before applying the patch if neither head contains the other.
        if ref:
            comparison = await worker.github.request(
                "GET", repository, f"compare/{current_sha}...{ref}"
            )
            if comparison.get("status") not in ("ahead", "identical"):
                raise SandboxError(
                    "Default branch moved beyond the existing PR; reconcile the branch before retrying"
                )
        context = {
            "run_id": run.id,
            "base_sha": run.base_sha,
            "source": run.source,
            "patch": run.patch,
            "checks": run.checks,
            "findings": run.findings,
            "deep_review": batch.deep_review,
            "version": run.plan_version,
            "branch": association.branch,
            "head_sha": ref,
            "target_sha": target_sha,
            "default_sha": current_sha,
            "default_branch": default_branch,
        }
        run.stage = "validating"
        event(
            session,
            run,
            "Applying the approved patch and independently rerunning repository validation",
        )
        await session.commit()
    workspace = worker.workspace_factory(worker.settings, context["run_id"].hex)
    with tempfile.TemporaryDirectory(prefix="gitaudit-patch-") as directory:
        root = Path(directory)
        before, after = await apply_patch(
            root,
            await worker.github.archive(repository, context["base_sha"]),
            await worker.github.archive(repository, target_sha),
            context["patch"],
            context["source"],
            context["base_sha"],
            context["findings"],
            context["deep_review"],
            worker.settings.audit_allow_workflow_edits,
        )
        # Standard checks plus the original required commands: removing a rule is not a pass.
        checks = discover(root)
        keys = {c.key for c in checks}
        for old in context["checks"]:
            if old.get("argv") and old["key"] not in keys:
                checks.append(Check(**{k: old[k] for k in Check.__dataclass_fields__ if k in old}))
        shutil.rmtree(root / ".git")
        try:
            await workspace.prepare(root)
            validation = await execute_checks(
                workspace,
                checks,
                target_sha,
                lambda message: worker.emit(job_id, token, "Validation: " + message),
            )
        finally:
            await workspace.cleanup()
    # GitHub checks cannot run on an unpublished patch. Keep them explicitly unverified.
    baseline = [c for c in context["checks"] if not c["key"].startswith("github:")]
    async with worker.factory() as session:
        control, _, run, batch = await worker.locked(session, job_id, token)
        if batch.stopped or control.paused or run.approved_version != context["version"]:
            return
        run.validation = validation
        if not validation_passes(baseline, validation):
            if run.corrections < 2:
                run.corrections += 1
                run.stage = "correcting"
                run.message = (
                    "Correction within the approved scope. Fix validation failures and return a new patch; do not publish a PR. "
                    + json_validation(validation)
                )
                event(
                    session,
                    run,
                    f"Validation failed; correction {run.corrections}/2 queued in the same session",
                )
            else:
                run.stage = "blocked"
                run.message = (
                    "Validation unresolved after two correction rounds; explicit retry required"
                )
                run.completed_at = now()
            await session.commit()
            return
        # Fetch the provider's latest plan before publishing so changed plans lose approval.
        await worker.poll(session, run, batch)
        if run.approved_version != context["version"]:
            await session.commit()
            return
        branch, sha = await worker.github.head(repository)
        if sha != context["default_sha"] or branch != context["default_branch"]:
            run.message = "Default branch moved during validation; reconciling and revalidating"
            await session.commit()
            return
        association = await session.get(AuditPRRecord, run.repository_id)
        if await worker.github.ref(repository, association.branch) != context["head_sha"]:
            raise SandboxError(
                "Human branch changes detected during validation; publication stopped"
            )
        parent = await worker.github.request("GET", repository, f"git/commits/{target_sha}")
        tree = []
        for name in sorted(set(before) | set(after)):
            if before.get(name) == after.get(name):
                continue
            if name not in after:
                tree.append({"path": name, "mode": before[name][1], "type": "blob", "sha": None})
            else:
                content, mode = after[name]
                blob = await worker.github.request(
                    "POST",
                    repository,
                    "git/blobs",
                    {"content": base64.b64encode(content).decode(), "encoding": "base64"},
                )
                tree.append({"path": name, "mode": mode, "type": "blob", "sha": blob["sha"]})
        if not tree:
            raise SandboxError("No nonempty validated change to publish")
        new_tree = await worker.github.request(
            "POST", repository, "git/trees", {"base_tree": parent["tree"]["sha"], "tree": tree}
        )
        commit = await worker.github.request(
            "POST",
            repository,
            "git/commits",
            {
                "message": f"GitAudit: repository check ({run.id})",
                "tree": new_tree["sha"],
                "parents": [target_sha],
            },
        )
        # Orphan blobs/commits may safely be regenerated; refs and PRs must be journaled.
        association.pending = {
            "run_id": str(run.id),
            "sha": commit["sha"],
            "expected_head": context["head_sha"],
            "default_sha": sha,
            "base": branch,
            "phase": "ref_ready",
            "title": f"GitAudit: Repository check — {repository}",
            "body": pr_body(worker, run, repository),
        }
        run.stage = "publishing"
        await session.commit()
        control, _, run, batch = await worker.locked(session, job_id, token)
        if batch.stopped or control.paused:
            return
        association = await session.get(AuditPRRecord, run.repository_id, populate_existing=True)
        await publish_pending(worker, session, run, batch, association, repository)
        await session.commit()


def json_validation(validation: list[dict]) -> str:
    """Bound correction evidence to the failed independent checks."""
    import json

    return json.dumps(
        [
            {"key": c["key"], "status": c["status"], "output": c["output"][-8000:]}
            for c in validation
            if c["status"] != "pass"
        ]
    )


async def publish_pending(worker, session, run, batch, association, repository: str) -> None:
    """Reconcile ref/PR uncertainty and never blindly repeat a possibly accepted write."""
    pending = dict(association.pending)
    if pending["run_id"] != str(run.id):
        raise ProviderError("Another run has an unresolved publication for this repository")
    if batch.stopped or run.approved_version != run.plan_version or not run.approved_version:
        return
    current = await worker.github.ref(repository, association.branch)
    if current not in (pending["expected_head"], pending["sha"]):
        raise SandboxError("Owned branch changed; preserving human edits")
    if current != pending["sha"]:
        if pending["phase"] == "ref_uncertain":
            run.message = (
                "GitHub ref write uncertain; waiting for positive reconciliation, no repeated write"
            )
            return
        _branch, sha = await worker.github.head(repository)
        if sha != pending["default_sha"]:
            association.pending = None
            run.stage = "validating"
            return
        pending["phase"] = "ref_uncertain"
        association.pending = pending
        await session.commit()
        # Serialize stop and publication using the same control row.
        from .audit_service import control_lock

        control = await control_lock(session)
        await session.refresh(batch)
        if batch.stopped or control.paused:
            return
        if pending["expected_head"] is None:
            await worker.github.request(
                "POST",
                repository,
                "git/refs",
                {"ref": f"refs/heads/{association.branch}", "sha": pending["sha"]},
            )
        else:
            await worker.github.request(
                "PATCH",
                repository,
                f"git/refs/heads/{quote(association.branch, safe='')}",
                {"sha": pending["sha"], "force": False},
            )
    association.head_sha = pending["sha"]
    pr = await worker.github.owned_pr(repository, association.branch)
    if pr is None:
        if pending["phase"] == "pr_uncertain":
            run.message = "GitHub PR creation uncertain; waiting for positive reconciliation"
            return
        pending["phase"] = "pr_uncertain"
        association.pending = pending
        await session.commit()
        from .audit_service import control_lock

        control = await control_lock(session)
        await session.refresh(batch)
        if batch.stopped or control.paused:
            return
        pr = await worker.github.request(
            "POST",
            repository,
            "pulls",
            {
                "head": association.branch,
                "base": pending["base"],
                "title": pending["title"],
                "body": pending["body"],
            },
        )
    if pr["base"]["ref"] != pending["base"]:
        raise SandboxError("Owned PR base was changed; publication requires attention")
    # Updating description is idempotent; preserve human text outside the owned block.
    marker_start, marker_end = "<!-- gitaudit:start -->", "<!-- gitaudit:end -->"
    body = pr.get("body") or ""
    block = f"{marker_start}\n{pending['body']}\n{marker_end}"
    if marker_start in body and marker_end in body:
        start, end = body.index(marker_start), body.index(marker_end) + len(marker_end)
        body = body[:start] + block + body[end:]
    elif body == pending["body"]:
        body = block
    else:
        body = body + "\n\n" + block
    await worker.github.request(
        "PATCH", repository, f"pulls/{pr['number']}", {"title": pending["title"], "body": body}
    )
    association.number, association.url, association.pending = pr["number"], pr["html_url"], None
    run.operation = None
    run.stage, run.completed_at = "pr_ready", now()
    run.message = "Independently validated repair published to the repository's owned PR"
    event(
        session,
        run,
        run.message,
        "publication",
        {"url": association.url, "head_sha": association.head_sha},
    )
