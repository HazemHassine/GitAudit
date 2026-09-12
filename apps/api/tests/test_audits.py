"""Offline acceptance scenarios for durable audits and one-PR orchestration."""

import io
import json
import tarfile
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from maintainer_api.audit_checks import digest, discover, execute_checks, validation_passes
from maintainer_api.audit_providers import GitHubAuditClient, JulesClient, ProviderError
from maintainer_api.audit_routes import stop_run
from maintainer_api.audit_service import create_batch, decide, now, quota, snapshot
from maintainer_api.audit_worker import AuditWorker, LeaseLost
from maintainer_api.config import Settings
from maintainer_api.database import (
    AuditControlRecord,
    AuditEventRecord,
    AuditJobRecord,
    AuditPRRecord,
    AuditRunRecord,
    Base,
    RepositoryRecord,
)
from maintainer_api.github import HttpGitHubReader
from maintainer_api.sandbox import DockerWorkspace, SandboxError, extract_source

SHA = "a" * 40
SOURCE = "sources/github-fixture"


def archive(files: dict[str, str]) -> bytes:
    """Create a GitHub-shaped tarball from trusted offline fixture files."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo("fixture/" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


@pytest.fixture
async def factory(tmp_path):
    """Use a file database so distinct API/worker sessions exercise persistence."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/audits.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(AuditControlRecord(id=1))
        await session.commit()
    yield factory
    await engine.dispose()


async def repository(factory, name="fixture"):
    """Create a connected repository without a live provider."""
    async with factory() as session:
        repo = RepositoryRecord(
            github_id=uuid4().int % 1_000_000,
            owner="owner",
            name=name,
            default_branch="main",
            html_url=f"https://github.com/owner/{name}",
        )
        session.add(repo)
        await session.commit()
        return repo


async def queued(factory, repo, **options):
    """Return the durable repository run after API admission."""
    async with factory() as session:
        batch = await create_batch(session, [repo.id], str(uuid4()), **options)
        return await session.scalar(
            select(AuditRunRecord).where(AuditRunRecord.batch_id == batch.id)
        )


class FakeWorkspace:
    """Execute fixture outcomes without invoking either repository code or Docker."""

    fail_install = False
    unavailable = False

    def __init__(self, settings, identity):
        self.calls = []
        self.image_id = "fixture-image-v1"
        self.files = {}

    async def prepare(self, root):
        self.files = {
            p.relative_to(root).as_posix(): p.read_text() for p in root.rglob("*") if p.is_file()
        }

    async def run(self, argv, directory=".", network=False):
        self.calls.append((argv, directory, network))
        if "--version" in argv or "-version" in argv or argv[-1] == "version":
            return (127, "missing") if self.unavailable else (0, "fixture-tool 1.0")
        if self.fail_install and ("ci" in argv or "venv" in " ".join(argv)):
            return 1, "Dependency installation failed"
        if argv[-1] == "coverage":
            return 3, "No coverage reports"
        if "test" in argv or "pytest" in argv:
            return (
                (1, "assert broken == fixed")
                if any(
                    "broken" in text
                    for name, text in self.files.items()
                    if name.endswith("code.txt")
                )
                else (0, "3 passed")
            )
        return 0, "check passed"

    async def cleanup(self):
        pass


class FakeGitHub:
    """Model ref ancestry, persisted PRs and idempotent read reconciliation."""

    def __init__(self, files):
        self.files = files
        self.sha = SHA
        self.refs = {}
        self.prs = []
        self.writes = []
        self.lose_pr_response = False
        self.changed_files = {}
        self.blobs = {}
        self.commit_files = {}

    async def head(self, repo):
        return "main", self.sha

    async def archive(self, repo, sha):
        return archive(self.commit_files.get(sha, self.files))

    async def evidence(self, repo, sha):
        return []

    async def ref(self, repo, branch):
        return self.refs.get(branch)

    async def owned_pr(self, repo, branch):
        return next(
            (p for p in self.prs if p["head"]["ref"] == branch and p["state"] == "open"), None
        )

    async def request(self, method, repo, path, data=None, params=None):
        if method != "GET":
            self.writes.append((method, path, data))
        if path.startswith("compare/"):
            return {"status": "ahead"}
        if path.startswith("git/commits/"):
            return {"tree": {"sha": "tree-base"}}
        if path == "git/blobs":
            import base64

            key = digest(data)
            self.blobs[key] = base64.b64decode(data["content"]).decode()
            return {"sha": key}
        if path == "git/trees":
            self.changed_files = data["tree"]
            return {"sha": "tree-new"}
        if path == "git/commits":
            key = digest(data)
            contents = dict(self.commit_files.get(data["parents"][0], self.files))
            for file in self.changed_files:
                if file["sha"] is None:
                    contents.pop(file["path"], None)
                else:
                    contents[file["path"]] = self.blobs[file["sha"]]
            self.commit_files[key] = contents
            return {"sha": key}
        if path == "git/refs":
            assert data["ref"][11:] not in self.refs
            self.refs[data["ref"][11:]] = data["sha"]
            return {}
        if path.startswith("git/refs/heads/"):
            from urllib.parse import unquote

            self.refs[unquote(path.split("heads/")[1])] = data["sha"]
            assert data["force"] is False
            return {}
        if path == "pulls" and method == "POST":
            pr = {
                "number": len(self.prs) + 1,
                "html_url": "https://github.com/owner/fixture/pull/1",
                "state": "open",
                "body": data["body"],
                "base": {"ref": data["base"]},
                "head": {"ref": data["head"]},
            }
            self.prs.append(pr)
            if self.lose_pr_response:
                self.lose_pr_response = False
                raise httpx.ReadTimeout("Accepted write; response lost")
            return pr
        if path.startswith("pulls/"):
            pr = self.prs[int(path.split("/")[1]) - 1]
            if method == "PATCH":
                pr.update(data)
            return pr
        raise AssertionError((method, path))


class FakeJules:
    """Model plans, completion patches and lost session-create responses."""

    def __init__(self):
        self.sessions = []
        self.events = []
        self.state = "AWAITING_PLAN_APPROVAL"
        self.creations = 0
        self.approvals = 0
        self.messages = []
        self.lose_create_response = False
        self.missing_source = False

    async def source(self, owner, repo):
        if self.missing_source:
            raise ProviderError("Connect repository in Jules", 404)
        return SOURCE

    async def create(self, source, branch, marker, prompt):
        self.creations += 1
        assert "findings" in json.loads(prompt)
        remote = {
            "name": f"sessions/{self.creations}",
            "title": marker,
            "state": "PLANNING",
            "sourceContext": {"source": source},
        }
        self.sessions.append(remote)
        self.plan("initial")
        if self.lose_create_response:
            raise httpx.ReadTimeout("Accepted session; response lost")
        return remote

    def plan(self, title):
        self.events.append(
            {
                "name": f"sessions/{self.creations}/activities/{len(self.events)}",
                "createTime": str(len(self.events)),
                "planGenerated": {
                    "plan": {
                        "id": title,
                        "steps": [
                            {
                                "id": "1",
                                "title": title,
                                "description": "Fix code.txt and verify tests",
                            }
                        ],
                    }
                },
            }
        )

    async def pages(self, path, key):
        return self.sessions

    async def activities(self, name):
        return self.events

    async def request(self, method, path, payload=None):
        if method == "GET":
            return {"state": self.state}
        if path.endswith(":approvePlan"):
            self.approvals += 1
            self.state = "IN_PROGRESS"
        else:
            self.messages.append(payload)
            self.state = "IN_PROGRESS"
        return {}

    def complete(self, diff=None, base=SHA):
        self.state = "COMPLETED"
        self.events.append(
            {
                "name": f"sessions/{self.creations}/activities/{len(self.events)}",
                "createTime": str(len(self.events)),
                "artifacts": [
                    {
                        "changeSet": {
                            "source": SOURCE,
                            "gitPatch": {
                                "baseCommitId": base,
                                "unidiffPatch": diff
                                or "diff --git a/code.txt b/code.txt\n--- a/code.txt\n+++ b/code.txt\n@@ -1 +1 @@\n-broken\n+fixed\n",
                            },
                        }
                    }
                ],
            }
        )


async def tick(worker):
    """Make the queued poll immediately due without sleeping through backoff."""
    async with worker.factory() as session:
        for job in (await session.scalars(select(AuditJobRecord))).all():
            job.available_at = now() - timedelta(seconds=1)
        await session.commit()
    await worker.tick()


async def row(factory, run):
    async with factory() as session:
        return await session.get(AuditRunRecord, run.id)


def source_files(stack="node", broken=True):
    """Python, Node and monorepo inputs share an evidenced test failure."""
    files = {"code.txt": "broken\n" if broken else "fixed\n"}
    if stack in ("node", "monorepo"):
        files.update(
            {
                "package.json": json.dumps(
                    {"scripts": {"test": "node --test"}, "workspaces": ["packages/*"]}
                ),
                "package-lock.json": "{}",
            }
        )
    if stack in ("python", "monorepo"):
        prefix = "apps/api/" if stack == "monorepo" else ""
        files[prefix + "pyproject.toml"] = (
            '[project]\nname="fixture"\nversion="1.0"\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n'
        )
    return files


async def ready_plan(factory, stack="node", **github_options):
    repo = await repository(factory)
    run = await queued(factory, repo)
    github, jules = FakeGitHub(source_files(stack)), FakeJules()
    for key, value in github_options.items():
        setattr(github, key, value)
    worker = AuditWorker(factory, Settings(_env_file=None), github, jules, FakeWorkspace)
    for _ in range(3):
        await tick(worker)
    current = await row(factory, run)
    assert current.stage == "awaiting_approval", current.message
    return worker, run, repo


@pytest.mark.parametrize("stack", ["python", "node", "monorepo"])
async def test_fixture_checks_plan_validation_and_one_pr(factory, stack):
    worker, run, _ = await ready_plan(factory, stack)
    current = await row(factory, run)
    assert current.findings and worker.jules.creations == 1 and worker.jules.approvals == 0
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "approval-one")
    await tick(worker)
    assert worker.jules.approvals == 1
    worker.jules.complete()
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "pr_ready", current.message
    assert len(worker.github.prs) == 1
    await tick(worker)
    assert len(worker.github.prs) == 1 and worker.jules.creations == 1


async def test_passing_repository_uses_no_session_or_pr(factory):
    repo = await repository(factory)
    run = await queued(factory, repo)
    worker = AuditWorker(
        factory,
        Settings(_env_file=None),
        FakeGitHub(source_files(broken=False)),
        FakeJules(),
        FakeWorkspace,
    )
    await tick(worker)
    current = await row(factory, run)
    assert current.stage in ("completed", "partial")
    assert worker.jules.creations == 0 and not worker.github.prs
    assert "No actionable findings" in current.message


async def test_idempotent_creation_and_request_conflict(factory):
    repo = await repository(factory)
    async with factory() as session:
        first = await create_batch(session, [repo.id, repo.id], "same-request")
        second = await create_batch(session, [repo.id], "same-request")
        assert first.id == second.id
        with pytest.raises(HTTPException, match="different repositories"):
            await create_batch(session, [repo.id], "same-request", deep_review=True)
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(AuditRunRecord)) == 1


async def test_lost_session_response_reconciles_without_duplicate(factory):
    repo = await repository(factory)
    run = await queued(factory, repo)
    jules = FakeJules()
    jules.lose_create_response = True
    worker = AuditWorker(
        factory, Settings(_env_file=None), FakeGitHub(source_files()), jules, FakeWorkspace
    )
    await tick(worker)
    await tick(worker)
    current = await row(factory, run)
    assert current.operation["kind"] == "create"
    # A fresh worker is a process restart, with no process-local provider history.
    worker = AuditWorker(factory, worker.settings, worker.github, jules, FakeWorkspace)
    await tick(worker)
    assert (await row(factory, run)).session_name == "sessions/1"
    assert jules.creations == 1


async def test_uncertain_absent_session_never_reposts(factory):
    repo = await repository(factory)
    run = await queued(factory, repo)
    jules = FakeJules()
    jules.lose_create_response = True
    worker = AuditWorker(
        factory, Settings(_env_file=None), FakeGitHub(source_files()), jules, FakeWorkspace
    )
    await tick(worker)
    await tick(worker)
    jules.sessions = []
    await tick(worker)
    await tick(worker)
    assert jules.creations == 1
    async with factory() as session:
        assert (await quota(session, worker.settings))["reserved"] == 1
    assert (await row(factory, run)).operation is not None


async def test_quota_exhaustion_queues_without_creation(factory):
    worker, run, repo = await ready_plan(factory)
    async with factory() as session:
        current = await session.get(AuditRunRecord, run.id)
        current.stage = "rejected"
        await session.commit()
    worker.jules.state = "FAILED"
    await tick(worker)
    second = await queued(factory, repo)
    worker.settings.audit_daily_sessions = 1
    await tick(worker)
    await tick(worker)
    assert (await row(factory, second)).stage == "quota_wait"
    assert worker.jules.creations == 1


@pytest.mark.parametrize("decision", ["reject", "revise"])
async def test_rejected_and_revised_plans_never_execute(factory, decision):
    worker, run, _ = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        await decide(
            session, run.id, current.plan_version, decision, "Change scope", "decision-key"
        )
    await tick(worker)
    assert worker.jules.approvals == 0 and not worker.github.prs
    if decision == "revise":
        assert len(worker.jules.messages) == 1 and worker.jules.creations == 1


async def test_superseded_plan_invalidates_approval_before_dispatch(factory):
    worker, run, _ = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "approve-old")
    worker.jules.plan("new scope")
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "awaiting_approval" and current.approved_version is None
    assert worker.jules.approvals == 0


async def test_stop_prevents_approval_but_keeps_remote_tracking(factory):
    worker, run, _ = await ready_plan(factory)
    async with factory() as session:
        await stop_run(run.batch_id, session)
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "stopped" and "cancellation" in current.message
    assert worker.jules.approvals == 0


async def test_lost_pr_response_reconciles_to_one_pr(factory):
    worker, run, _ = await ready_plan(factory, lose_pr_response=True)
    current = await row(factory, run)
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "approval-key")
    await tick(worker)
    worker.jules.complete()
    await tick(worker)
    assert len(worker.github.prs) == 1
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "pr_ready", current.message
    assert len(worker.github.prs) == 1


async def test_wrong_base_patch_is_blocked(factory):
    worker, run, _ = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "approval-key")
    await tick(worker)
    worker.jules.complete(base="b" * 40)
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "blocked" and "base commit" in current.message
    assert not worker.github.prs


async def test_human_commits_on_owned_branch_are_preserved(factory):
    worker, run, repo = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        session.add(AuditPRRecord(repository_id=repo.id, branch="gitaudit/owned", head_sha="owned"))
        await session.commit()
        await decide(session, run.id, current.plan_version, "approve", "", "approval-key")
    worker.github.refs["gitaudit/owned"] = "human"
    await tick(worker)
    worker.jules.complete()
    await tick(worker)
    assert worker.github.refs["gitaudit/owned"] == "human"
    assert (await row(factory, run)).stage == "blocked"
    assert not worker.github.writes


async def test_lease_recovery_and_stale_owner_fencing(factory):
    repo = await repository(factory)
    await queued(factory, repo)
    worker = AuditWorker(
        factory, Settings(_env_file=None), FakeGitHub(source_files()), FakeJules(), FakeWorkspace
    )
    job_id, old_token = await worker.claim()
    assert await worker.claim() is None
    async with factory() as session:
        job = await session.get(AuditJobRecord, job_id)
        job.lease_until = now() - timedelta(seconds=1)
        await session.commit()
    _, new_token = await worker.claim()
    assert new_token != old_token
    async with factory() as session:
        with pytest.raises(LeaseLost):
            await worker.locked(session, job_id, old_token)


async def test_restored_report_and_deduplicated_activities(factory):
    worker, run, _ = await ready_plan(factory)
    await tick(worker)
    await tick(worker)
    async with factory() as session:
        report = await snapshot(session, run.batch_id)
        events = (
            await session.scalars(select(AuditEventRecord).where(AuditEventRecord.kind == "jules"))
        ).all()
    assert report["repositories"][0]["plan"] and report["repositories"][0]["checks"]
    assert len(events) == 1


async def test_missing_docker_never_runs_host_command(tmp_path, monkeypatch):
    from maintainer_api import sandbox

    calls = []

    async def missing(*args, **kwargs):
        calls.append(args)
        raise FileNotFoundError("docker")

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", missing)
    workspace = DockerWorkspace(Settings(_env_file=None), uuid4().hex)
    with pytest.raises(SandboxError, match="host fallback disabled"):
        await workspace.prepare(tmp_path)
    assert len(calls) == 1 and calls[0][0] == "docker"


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../outside", tarfile.REGTYPE),
        ("root/link", tarfile.SYMTYPE),
        ("root/.git/config", tarfile.REGTYPE),
    ],
)
def test_archive_rejects_traversal_links_and_git_metadata(tmp_path, name, kind):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.type = kind
        tar.addfile(info)
    with pytest.raises(SandboxError):
        extract_source(output.getvalue(), tmp_path)


async def test_missing_lockfile_and_failed_install_are_not_passes(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"node --test"}}')
    checks = discover(tmp_path)
    workspace = FakeWorkspace(None, "fixture")
    await workspace.prepare(tmp_path)

    async def emit(message):
        pass

    results = await execute_checks(workspace, checks, SHA, emit)
    assert next(c for c in results if c["key"] == ".:test")["status"] == "missing_configuration"
    (tmp_path / "package-lock.json").write_text("{}")
    workspace.fail_install = True
    results = await execute_checks(workspace, discover(tmp_path), SHA, emit)
    assert next(c for c in results if c["key"] == ".:test")["status"] == "installation_failed"


def test_validation_rejects_regressions_and_empty_coverage():
    before = [
        {"key": "tests", "status": "pass", "area": "tests"},
        {"key": "build", "status": "fail", "area": "build"},
    ]
    assert not validation_passes(before, [])
    assert not validation_passes(before, [{"key": "tests", "status": "fail", "area": "tests"}])
    assert validation_passes(before, [{**c, "status": "pass"} for c in before])


async def test_sources_pagination_and_creation_contract():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["sourceContext"]["source"] == "sources/opaque-id"
            assert payload["requirePlanApproval"] is True
            assert payload["automationMode"] == "AUTOMATION_MODE_UNSPECIFIED"
            return httpx.Response(200, json={"name": "sessions/1"})
        if request.url.params.get("pageToken"):
            return httpx.Response(
                200,
                json={
                    "sources": [
                        {
                            "name": "sources/opaque-id",
                            "githubRepo": {"owner": "owner", "repo": "repo"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"sources": [], "nextPageToken": "next"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        jules = JulesClient(Settings(_env_file=None, jules_api_key="fixture"), client)
        assert await jules.source("owner", "repo") == "sources/opaque-id"
        await jules.create("sources/opaque-id", "main", "marker", "repair")
    assert len(requests) == 3


async def test_security_evidence_never_persists_raw_secrets():
    def handle(request):
        if "secret-scanning" in request.url.path:
            return httpx.Response(200, json=[{"secret": "never-persist-this"}])
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        github = GitHubAuditClient(
            HttpGitHubReader(Settings(_env_file=None, github_token="fixture"), client)
        )
        results = await github.evidence("owner/repo", SHA)
    assert "never-persist-this" not in json.dumps(results)
    assert any(r["status"] == "unavailable" for r in results)
    assert results[-1]["status"] == "fail"


async def test_owner_api_login_replay_settings_decisions_stop_and_history(factory, monkeypatch):
    """Exercise the authenticated API surface and replay cursors against persisted data."""
    from pydantic import SecretStr
    from starlette.requests import Request

    from maintainer_api.audit_routes import stream_events
    from maintainer_api.main import app, settings

    monkeypatch.setattr(settings, "owner_password", SecretStr("test-owner-secret"))
    monkeypatch.setattr(settings, "owner_session_secret", None)
    monkeypatch.setattr(app.state, "session_factory", factory, raising=False)
    repo = await repository(factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/api/v1/audits/runs", json={"repository_ids": [str(repo.id)]})
        ).status_code == 401
        assert (await client.get("/api/v1/audits/runs")).status_code == 401
        assert (
            await client.post("/api/v1/auth/login", json={"password": "wrong"})
        ).status_code == 401
        assert (
            await client.post(
                "/api/v1/auth/login",
                json={"password": "test-owner-secret"},
                headers={"Origin": "https://attacker.invalid"},
            )
        ).status_code == 403
        login = await client.post("/api/v1/auth/login", json={"password": "test-owner-secret"})
        assert login.status_code == 200 and "HttpOnly" in login.headers["set-cookie"]
        assert (await client.get("/api/v1/auth/session")).json()["authenticated"]
        saved = await client.put("/api/v1/audits/settings", json={"repository_ids": [str(repo.id)]})
        assert saved.status_code == 200
        assert (await client.get("/api/v1/audits/settings")).json() == saved.json()
        payload = {"repository_ids": [str(repo.id)]}
        assert (await client.post("/api/v1/audits/runs", json=payload)).status_code == 422
        created = await client.post(
            "/api/v1/audits/runs", json=payload, headers={"Idempotency-Key": "api-run-key"}
        )
        assert created.status_code == 202, created.text
        batch = created.json()
        repeated = await client.post(
            "/api/v1/audits/runs", json=payload, headers={"Idempotency-Key": "api-run-key"}
        )
        assert repeated.json()["id"] == batch["id"]
        assert len((await client.get("/api/v1/audits/runs")).json()) == 1
        events = (await client.get(f"/api/v1/audits/runs/{batch['id']}/events")).json()
        assert (
            events
            and not (
                await client.get(
                    f"/api/v1/audits/runs/{batch['id']}/events?after={events[-1]['id']}"
                )
            ).json()
        )
        status = (await client.get("/api/v1/audits/status")).json()
        assert status["quota"]["limit"] == 80 and not status["worker_online"]
        assert (await client.post("/api/v1/audits/queue/pause")).json()["paused"]
        assert not (await client.post("/api/v1/audits/queue/resume")).json()["paused"]
        stopped = await client.post(f"/api/v1/audits/runs/{batch['id']}/stop")
        assert stopped.json()["stopped"]
        assert (await client.get(f"/api/v1/audits/runs/{batch['id']}")).json()["stopped"]
        missing = await client.get(f"/api/v1/audits/runs/{uuid4()}")
        assert missing.status_code == 404
        assert (await client.post("/api/v1/auth/logout")).status_code == 200
        assert not (await client.get("/api/v1/auth/session")).json()["authenticated"]
        client.cookies.set("gitaudit_owner", "invalid-signature")
        assert not (await client.get("/api/v1/auth/session")).json()["authenticated"]

    # Read one actual SSE event without leaving an unbounded ASGI stream open.
    async def receive():
        return {"type": "http.request"}

    request = Request({"type": "http", "method": "GET", "headers": [], "app": app}, receive)
    async with factory() as session:
        from uuid import UUID

        response = await stream_events(UUID(batch["id"]), request, session, None, 0)
        first = await anext(response.body_iterator)
        assert "id: " in first and "event: audit" in first
        await response.body_iterator.aclose()
        with pytest.raises(HTTPException):
            await stream_events(UUID(batch["id"]), request, session, "invalid", 0)


async def test_api_plan_version_and_retry_protection(factory, monkeypatch):
    from pydantic import SecretStr

    from maintainer_api.main import app, settings

    _worker, run, _ = await ready_plan(factory)
    monkeypatch.setattr(settings, "owner_password", SecretStr("owner-test"))
    monkeypatch.setattr(app.state, "session_factory", factory, raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer owner-test"},
    ) as client:
        url = f"/api/v1/audits/repositories/{run.id}/decision"
        key = {"Idempotency-Key": "api-approval"}
        current = await row(factory, run)
        payload = {"version": current.plan_version, "decision": "approve"}
        assert (
            await client.post(url, json={**payload, "version": "0" * 64}, headers=key)
        ).status_code == 409
        assert (
            await client.post(url, json={**payload, "decision": "revise"}, headers=key)
        ).status_code == 422
        approved = await client.post(url, json=payload, headers=key)
        assert approved.status_code == 200
        assert (await client.post(url, json=payload, headers=key)).status_code == 200
        assert (
            await client.post(url, json={**payload, "decision": "reject"}, headers=key)
        ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/audits/repositories/{run.id}/retry",
                headers={"Idempotency-Key": "retry-key"},
            )
        ).status_code == 409


async def test_subsequent_approved_run_updates_same_pr_and_keeps_human_description(factory):
    worker, run, repo = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "first-plan")
    await tick(worker)
    worker.jules.complete()
    await tick(worker)
    assert (await row(factory, run)).stage == "pr_ready"
    worker.github.prs[0]["body"] += "\nHuman reviewer note: keep this."
    second = await queued(factory, repo, deep_review=True, force=True)
    worker.jules.events = []
    worker.jules.state = "AWAITING_PLAN_APPROVAL"
    for _ in range(3):
        await tick(worker)
    current = await row(factory, second)
    assert current.stage == "awaiting_approval", current.message
    async with factory() as session:
        await decide(session, second.id, current.plan_version, "approve", "", "second-plan")
    await tick(worker)
    worker.jules.complete(
        "diff --git a/docs/repair.md b/docs/repair.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/repair.md\n@@ -0,0 +1 @@\n+Repair verified.\n"
    )
    await tick(worker)
    current = await row(factory, second)
    assert current.stage == "pr_ready", current.message
    assert len(worker.github.prs) == 1
    assert "Human reviewer note: keep this." in worker.github.prs[0]["body"]
    assert (
        sum(method == "POST" and path == "pulls" for method, path, _ in worker.github.writes) == 1
    )


async def test_provider_rate_limit_releases_known_rejection_and_defers(factory):
    repo = await repository(factory)
    run = await queued(factory, repo)
    jules = FakeJules()

    async def rejected(*args):
        raise ProviderError("Quota exhausted", 429)

    jules.create = rejected
    worker = AuditWorker(
        factory, Settings(_env_file=None), FakeGitHub(source_files()), jules, FakeWorkspace
    )
    await tick(worker)
    await tick(worker)
    assert (await row(factory, run)).stage == "quota_wait"
    async with factory() as session:
        budget = await quota(session, worker.settings)
        assert budget["reserved"] == 0 and budget["provider_retry_at"]


async def test_missing_source_preserves_deterministic_audit(factory):
    repo = await repository(factory)
    run = await queued(factory, repo)
    jules = FakeJules()
    jules.missing_source = True
    worker = AuditWorker(
        factory, Settings(_env_file=None), FakeGitHub(source_files()), jules, FakeWorkspace
    )
    await tick(worker)
    await tick(worker)
    current = await row(factory, run)
    assert current.stage == "blocked" and current.checks and "Connect" in current.message
    assert jules.creations == 0


async def test_cache_reuses_checks_but_refreshes_network_evidence(factory):
    repo = await repository(factory)
    first = await queued(factory, repo)
    worker = AuditWorker(
        factory,
        Settings(_env_file=None),
        FakeGitHub(source_files(broken=False)),
        FakeJules(),
        FakeWorkspace,
    )
    await tick(worker)
    assert (await row(factory, first)).stage == "partial"
    second = await queued(factory, repo)
    await tick(worker)
    current = await row(factory, second)
    assert any(c.get("cached") for c in current.checks)
    assert not next(c for c in current.checks if c["key"] == ".:npm-audit")["cached"]


async def test_legacy_jules_launch_uses_shared_budget_service(factory):
    from maintainer_api.domain import CreateJulesSessionRequest
    from maintainer_api.jules import JulesAuditService

    repo = await repository(factory)
    async with factory() as session:
        control = await session.get(AuditControlRecord, 1)
        control.selected = [str(repo.id)]
        await session.commit()
    service = JulesAuditService(Settings(_env_file=None, jules_api_key="fixture"), factory)
    request = CreateJulesSessionRequest(
        audit_area="build", dry_run=False, idempotency_key="legacy-key"
    )
    first = await service.create_session(request)
    second = await service.create_session(request)
    assert first.session_id == second.session_id and first.session_id.startswith("audit-")
    assert service.list_sessions()
    assert service.review_targets("build")
    preview = await service.create_session(
        CreateJulesSessionRequest(audit_area="maintenance", dry_run=True)
    )
    assert preview.status == "preview"
    service.factory = None
    assert (await service.create_session(request)).status == "failed"


async def test_sandbox_argv_limits_network_and_cleanup_without_docker(tmp_path, monkeypatch):
    from maintainer_api import sandbox

    calls = []

    async def fake_command(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return 0, "sha256:fixture"
        return 0, ""

    monkeypatch.setattr(sandbox, "command", fake_command)
    workspace = DockerWorkspace(Settings(_env_file=None), "test-fixture")
    await workspace.prepare(tmp_path)
    await workspace.run(["npm", "ci"], network=True)
    await workspace.run(["npm", "test"])
    await workspace.cleanup()
    runs = [args for args in calls if args[:2] == ("docker", "run")]
    assert len(runs) == 2
    for args in runs:
        assert "--read-only" in args and "--cap-drop=ALL" in args
        assert "--pids-limit=256" in args and "--memory=2g" in args
        assert not any("docker.sock" in arg or "GITHUB_TOKEN" in arg for arg in args)
    assert "gitaudit-install" in runs[0] and "none" in runs[1]
    assert any(args[:3] == ("docker", "volume", "rm") for args in calls)


async def test_corrections_are_bounded_even_when_jules_returns_the_same_failed_patch(factory):
    worker, run, _ = await ready_plan(factory)
    current = await row(factory, run)
    async with factory() as session:
        await decide(session, run.id, current.plan_version, "approve", "", "bounded-correction")
    await tick(worker)
    bad = "diff --git a/code.txt b/code.txt\n--- a/code.txt\n+++ b/code.txt\n@@ -1 +1 @@\n-broken\n+still broken\n"
    for _ in range(3):
        worker.jules.complete(bad)
        await tick(worker)
        if (await row(factory, run)).stage == "correcting":
            await tick(worker)
    current = await row(factory, run)
    assert current.stage == "blocked", current.message
    assert current.corrections == 2 and len(worker.jules.messages) == 2
    assert worker.jules.creations == 1 and not worker.github.prs
