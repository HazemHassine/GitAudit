# GitAudit

[![CI](https://github.com/HazemHassine/GitAudit/actions/workflows/ci.yml/badge.svg)](https://github.com/HazemHassine/GitAudit/actions/workflows/ci.yml)

**An evidence-first console for auditing GitHub repositories and coordinating reviewed repairs.**

GitAudit inventories authorized repositories, records exact-commit CI evidence and scan history,
and coordinates repository checks and approval-based repair plans. The overview remains at `/`;
the dedicated workflow is at `/audits`, with permanent reports at `/audits/runs/{id}`.

## Audit workflow

1. Sign in with your local owner password, select repositories, and choose **Run checks**.
2. A separate worker checks each repository's default-branch commit in disposable Docker
   containers. Results include the command, tool version, commit, timestamps and bounded output.
3. Actionable failures are combined into one Jules repair session per repository. **Deep review**
   also requests a plan for otherwise passing repositories. No actionable findings means no
   automatic session or empty PR.
4. Review the actual plan and approve, reject, or request a revision. Approvals apply to the
   displayed plan version. Changed plans require another approval. Selected plans can be approved
   together; changes and publication then proceed without another routine confirmation.
5. GitAudit verifies patch provenance and scope, reruns independent checks, and publishes to its
   recorded branch and PR: **`GitAudit: Repository check — <repository>`**. Review and merge yourself.

Runs, jobs, events, decisions, quota reservations and PR associations live in PostgreSQL. Browser
refreshes restore history. Events use SSE replay with polling for state recovery. Queue pause and
resume control new actions; stopping prevents further local approvals and publication. The Jules
API does not guarantee cancellation of remote execution, so stopped remote sessions remain tracked.

## Local setup

Requires Docker with Compose. Source development also requires Python 3.12+ and Node 20.19+.

```bash
cp .env.example .env
```

Set these values in `.env`:

- `OWNER_PASSWORD`: a long unique owner password; all mutation endpoints require owner login.
- `OWNER_SESSION_SECRET`: an optional separate signing secret. Login cookies expire after 12 hours.
- GitHub authentication: either `GITHUB_TOKEN`, or the existing GitHub App settings
  (`GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, and private key/value or file path).
- `JULES_API_KEY`: optional for deterministic audits; required for repair planning.
- `DOCKER_GID`: the group ID owning `/var/run/docker.sock`, obtained with
  `stat -c '%g' /var/run/docker.sock`. This grants the dedicated worker access to Docker.

For GitHub, grant repository metadata, contents and Actions/check read access for selected
repositories. Repair publication additionally requires Contents and Pull Requests write access.
Security alerts need their corresponding read permissions. Workflow changes are blocked unless
`AUDIT_ALLOW_WORKFLOW_EDITS=true` and the credential has appropriate workflow permissions.
Connect each repair target to Jules; source identifiers are discovered through its Sources API.

```bash
docker compose --profile build-tools build checks
docker compose up --build -d
```

Open `http://localhost:3000/audits`. API documentation is at `http://localhost:8001/docs`.
Compose binds web, API and PostgreSQL ports to loopback. Public deployment and multiple owners
are outside this version. The API runs migrations before becoming ready; the worker waits for it.

Only the trusted worker receives the Docker socket and provider credentials. Check containers
receive source through a disposable volume, never credentials or that socket. Tests/builds have
networking disabled, a read-only root filesystem, CPU/memory/PID limits and deadlines. Installation
uses an internal Docker network and a CONNECT proxy restricted to PyPI and npm/Yarn registries.
Private registries, Git dependencies and network-dependent tests require explicit deployment
configuration; their absence is reported rather than silently using host execution.

## Checks and limits

- Python: pyproject/requirements detection, frozen uv installation where a lockfile exists,
  configured pytest, Ruff, mypy, package builds and resolved-dependency vulnerability checks.
- Node: npm lockfile installation and audit, existing test/build/typecheck/lint/documentation
  scripts, and workspace discovery. Yarn/pnpm rules remain visible when their tools are unavailable.
- CI/security/deployment: actionlint, gitleaks, GitHub checks and security evidence, Hadolint and
  Compose validation. Terraform formatting is detected but unavailable in the default image.
- Documentation: relative Markdown file links and configured documentation scripts. External URLs
  and anchors are not checked by the offline helper.
- Existing coverage reports are recorded without imposing GitAudit's own coverage target.
  Missing reports, unsupported projects, unavailable tools and failed installation remain visible.

Deterministic results are cached by repository, commit, check configuration, adapter version and
image identity. GitHub and vulnerability evidence refresh on subsequent runs; **Force recheck**
bypasses deterministic caches. The initial limits are two local jobs, three active Jules slots and
80 new Jules sessions per rolling 24 hours. The app budget does not guarantee account-wide capacity.
Uncertain creations retain a reservation until positively reconciled. Provider throttling queues
work. Corrections are limited to two within the same session; additional sessions require retry.

GitAudit never matches PR ownership by title or force-pushes over human commits. It preserves human
PR description text outside its marked report block. A changed owned branch requires attention.
Patches can be reconciled onto a moved default branch when there is no existing divergent PR;
a divergent existing PR currently requires branch reconciliation before retry. Symlinks, protected
paths, wrong-base patches, removed test/configuration files and unvalidated changes are blocked.
Uncertain ref/PR writes are reconciled by exact owned ref/PR identity; absent evidence does not
trigger another creation. An unresolved write may therefore require provider-side investigation.

## API and CLI

Audit resources use `/api/v1/audits`: `settings`, `status`, `queue/{pause|resume}`, `runs`,
`runs/{id}`, `runs/{id}/{events|stream|stop}`, and `repositories/{id}/{decision|retry}`.
Creation, plan decisions and retries require `Idempotency-Key`. Cookie-based browser requests use
owner login; local automation may use `Authorization: Bearer <OWNER_PASSWORD>`.

Existing repository scan/history and reproduction-history routes remain available. Legacy
reproduction launches now queue manifest-driven audit checks. Legacy Jules/coverage/CI live
launches delegate to the same backend service, require `idempotency_key`, and use the single
repository selected in Audits. Jules previews remain local and consume no sessions.

```bash
# Preview only: no credentials or provider calls.
python scripts/jules_audit.py --area security

# Queue through the local backend; reuse the key if the response is lost.
GITAUDIT_OWNER_PASSWORD='your-owner-password' python scripts/jules_audit.py \
  --live --repository-id '<connected-repository-uuid>' --idempotency-key 'my-review-request-001'
```

The manual GitHub workflow previews on a hosted runner. Live dispatch requires a trusted
self-hosted runner labelled `gitaudit` that can reach the local backend, the
`GITAUDIT_OWNER_PASSWORD` secret, and the `GITAUDIT_REPOSITORY_ID` variable. It does not bypass
backend quota or create Jules sessions directly.

## Development and verification

```bash
make install
make db-upgrade
make dev
# In another terminal:
.venv/bin/python -m maintainer_api.audit_worker

make test
make test-e2e
make build
.venv/bin/python scripts/export_openapi.py --check
.venv/bin/python scripts/export_audit_types.py --check
```

Offline fixtures cover Python, Node and monorepo check-to-PR flows, quota exhaustion, lost provider
responses, plan supersession/rejection, stop controls, lease recovery, repeat PR updates and human
edit protection. Jules modules participate in the coverage gate. Public docstrings in the new
orchestration modules are checked by `make lint-audit-docstrings`.

Opt-in Docker isolation tests use `GITAUDIT_DOCKER_TESTS=1`; PostgreSQL concurrency tests use
`AUDIT_TEST_DATABASE_URL` pointing to an **isolated migrated test database**. They do not call live
providers. Never point the PostgreSQL concurrency test at your application database.

**Live verification remains deferred.** Before treating the integration as production-proven,
a separately authorized pilot must demonstrate plan approval, patch retrieval, independent
validation, PR creation and an update to that same PR on one disposable repository, capped at two
live Jules sessions. Development work does not authorize that pilot.
