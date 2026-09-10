# GitAudit: Build System & Deployment Configuration (Issues #2 & #7)

This document records the architectural design, implementation details, and coordinator verification procedures for the deterministic portions of **Issue #2 (Audit: Build System)** and **Issue #7 (Audit: Deployment Configuration)**.

---

## 1. Summary of Changes

### Issue #2: Build System (Deterministic Scope)
1. **Strict TypeScript Compilation (`noUncheckedIndexedAccess: true`):**
   - Enabled `noUncheckedIndexedAccess: true` in [`apps/web/tsconfig.json`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/tsconfig.json).
   - Applied safe indexed-access fixes across frontend components:
     - [`apps/web/app/components/PunchCard.tsx`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/app/components/PunchCard.tsx): Safe retrieval and null-checks on `payload[0]` tooltip payload and nullish coalescing on `days[tick]` formatter.
     - [`apps/web/app/page.tsx`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/app/page.tsx): Safely increment accumulator counts with `Record<RepositoryStatus, number>` type and `(result[status] ?? 0) + 1`.
     - [`apps/web/app/components/LanguageBar.tsx`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/app/components/LanguageBar.tsx): Safe tuple sorting with fallback `(b[1] ?? 0) - (a[1] ?? 0)`.
     - [`apps/web/app/repositories/[repositoryId]/page.tsx`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/app/repositories/%5BrepositoryId%5D/page.tsx): Guarded `previousCompleted` scan access with length check.

2. **Next.js 16 Standalone Output & Strict Build:**
   - Configured `output: "standalone"` and `typescript.ignoreBuildErrors: false` in [`apps/web/next.config.mjs`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/next.config.mjs).
   - Created [`apps/web/public/.gitkeep`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/public/.gitkeep) to ensure public asset directory existence in multi-stage builds.

3. **Deterministic Client JS Compressed Bundle Budget Check:**
   - Created standalone Node.js checker [`scripts/check_bundle_budget.mjs`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/scripts/check_bundle_budget.mjs).
   - Inspects Next.js 16 Turbopack/Webpack output (`.next/build-manifest.json` and `.next/static/chunks/`) without requiring heavy or optional analyzer dependencies.
   - Enforces three deterministic gzip compressed budgets:
     - Max Single Chunk: **150 KB gzip** (largest vendor chunk is React DOM at ~75 KB).
     - Initial Root Bundle (`rootMainFiles` + `polyfillFiles`): **250 KB gzip** (currently ~128 KB).
     - Total Client JS Chunks: **400 KB gzip** (currently ~210 KB).
   - Added `check:bundle` script to [`apps/web/package.json`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/package.json) and `check-bundle` target to [`Makefile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/Makefile).

4. **Python Wheel Build & Integrity Check:**
   - Configured `strict-naming = true` for hatchling wheel target in [`apps/api/pyproject.toml`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/api/pyproject.toml).
   - Added PyPA `build>=1.2,<2` and `hatchling>=1.25,<2` to `[project.optional-dependencies] dev`.
   - Added `make build-wheel` and `make build-api` targets to [`Makefile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/Makefile) building with `--no-isolation` and verifying zip archive integrity with Python `zipfile.testzip()`.
   - Wired `build` target in [`Makefile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/Makefile) to run `build-web`, `check-bundle`, and `build-wheel`.

---

### Issue #7: Deployment Configuration (Deterministic Scope)
1. **Cache-Efficient Multi-Stage API Container:**
   - Resolved broken `pip install .` before `src/` exists in [`apps/api/Dockerfile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/api/Dockerfile).
   - Multi-stage architecture:
     - `builder`: creates `/opt/venv`, installs dependencies from `pyproject.toml` using package stub for maximal Docker layer caching, then copies `src/` and installs the package without re-downloading dependencies.
     - `runner`: copies minimal self-contained `/opt/venv` and application files; runs as non-root user `appuser:appgroup` (`uid=10001, gid=10001`).
     - Added container `HEALTHCHECK` verifying `/readyz` endpoint.

2. **Graceful SIGTERM Handling (API & Web):**
   - API: Created [`apps/api/docker-entrypoint.sh`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/api/docker-entrypoint.sh) running `alembic -c alembic.ini upgrade head` and replacing PID 1 via `exec "$@"`. Uvicorn receives `SIGTERM` directly from Docker.
   - Web: Standalone Next.js runner in [`apps/web/Dockerfile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/apps/web/Dockerfile) executes `CMD ["node", "server.js"]` as PID 1 directly under non-root `nextjs:nodejs` (`uid=1001, gid=1001`), bypassing non-forwarding npm wrappers.

3. **Docker Compose Validation:**
   - Added `validate-compose` target to [`Makefile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/Makefile) using `docker compose config --quiet`.
   - Added healthcheck for `web` service in [`docker-compose.yml`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/docker-compose.yml) verifying HTTP availability via `wget`.

4. **Hadolint & Checkov IaC Linting with Justified Suppressions:**
   - Created [`.hadolint.yaml`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/.hadolint.yaml) with documented suppressions (`DL3008`, `DL3013`).
   - Created [`.checkov.yaml`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/.checkov.yaml) with documented suppressions (`CKV_COMPOSE_1`, `CKV_COMPOSE_2`).
   - Added `make lint-docker` and `make lint-iac` targets to [`Makefile`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/Makefile).
   - Wired Compose validation, Hadolint (API + Web), and Checkov security scanning directly into [`.github/workflows/ci.yml`](file:///home/hazem/dev/02_Productivity_and_Tools/github_maintainer/.github/workflows/ci.yml).

---

## 2. Documented Justified Suppressions

| Tool | Rule ID | Scope | Justification |
| :--- | :--- | :--- | :--- |
| **Hadolint** | `DL3008` | `apps/api/Dockerfile` | Pinning Debian package patch versions in slim base images breaks builds unpredictably when upstream package mirrors retire older point releases. Minimal footprint is preserved via `--no-install-recommends` and `rm -rf /var/lib/apt/lists/*`. |
| **Hadolint** | `DL3013` | `apps/api/Dockerfile` | Internal project dependencies are managed and constrained by `pyproject.toml` rather than top-level `pip install` CLI version flags. |
| **Checkov** | `CKV_COMPOSE_1` | `docker-compose.yml` | `docker-compose.yml` is used for developer workstations and integration tests. Setting hardcoded CPU and memory limits causes developer environment instability and out-of-memory crashes across diverse developer machine specifications. |
| **Checkov** | `CKV_COMPOSE_2` | `docker-compose.yml` | Developer services require read-write access to local disks (PostgreSQL data volume, temporary log/socket files, Next.js cache). |

---

## 3. Coordinator Verification Instructions

The coordinator can verify all implementations locally and deterministically using the following steps:

### A. TypeScript Strictness & Typechecking
```bash
# Verify zero compiler warnings or errors with strict noUncheckedIndexedAccess:
npm --prefix apps/web run typecheck
```
*Expected output:* `next typegen` completes and `tsc` exits with status `0`.

### B. Production Web Build & Client JS Bundle Budget Check
```bash
# Build web production output and verify compressed client JS budgets:
make build-web
make check-bundle
```
*Expected output:*
- Next.js compiles standalone output to `apps/web/.next/standalone`.
- `scripts/check_bundle_budget.mjs` displays a table of all client JS chunks with gzip sizes and reports:
  `✓ SUCCESS: All client JavaScript compressed bundle budgets PASSED.` (exit code `0`).

### C. Python Wheel Build & Archive Integrity Check
```bash
# Build API wheel without isolation and verify zip archive integrity:
make build-wheel
```
*Expected output:*
- Wheel generated at `dist/gitaudit_api-0.1.0-py3-none-any.whl`.
- Python integrity test passes: `Verified wheel archive integrity: [...]` (exit code `0`).

### D. Full Unified Build Check
```bash
# Runs web build, bundle budget check, and wheel build in sequence:
make build
```
*Expected output:* All three stages pass with status `0`.

### E. Existing Test Suite & CI Workflow Linting Preservation
```bash
# Verify full test suite (pytest, ruff, actionlint, eslint, typecheck):
make test
```
*Expected output:*
- Pytest suite passes (>=80% coverage).
- Ruff check passes.
- Actionlint passes with 0 errors across all workflow files.
- ESLint passes with 0 warnings.
- TypeScript passes with 0 errors.

### F. Docker Compose & IaC Validation
```bash
# Validate Compose configuration syntax:
make validate-compose

# (Optional: If local hadolint or checkov container runners are available)
make lint-docker
make lint-iac
```
*Expected output:* Compose config validates quietly (exit code `0`).

### G. Docker Image Build Verification
```bash
# Verify both multi-stage Dockerfiles build successfully:
docker compose build
```
*Expected output:* Both `api` and `web` images build successfully without layer failure.

---

## 4. Known Limitations & Subsequent Scope

1. **Issues #2 and #7 Tracker Status:**
   - In accordance with instructions, issues are **not** marked complete in `docs/ISSUES.md` and `docs/ANTIGRAVITY_PROGRESS.md` is preserved without edits.
2. **UI & Jules Agent Integration:**
   - Active health dashboard cards (`BuildAuditCard`, `DeploymentAuditCard`) and automated Jules API prompt workflows for build caching and deployment audits are deferred to the subsequent dedicated UI/Jules shared assignment.
3. **Checkov / Hadolint in Restricted Environments:**
   - In local sandboxed environments without Docker daemon access, `make validate-compose` validates Compose syntax natively; Hadolint and Checkov steps run in GitHub Actions CI via official container actions.
