# GitAudit Open Issues Master Guide & Tracker

This document provides a comprehensive tracking register, technical architectural specifications, and implementation guidance for all open issues in GitAudit. It is designed so that any AI agent or human contributor can understand what is required for each audit domain and immediately pick up any issue.

---

## 📌 Active Work Register

| Property | Value |
| :--- | :--- |
| **Current Active Branch** | `audit/issue-4-ci-pipelines` |
| **Active Issue** | **[Issue #4: Audit: CI Pipelines](https://github.com/HazemHassine/GitAudit/issues/4)** |
| **Active Agent** | Antigravity Pairing Assistant |
| **Status** | In Progress |

---

## 🗺️ Issues Summary Matrix

| Issue ID | Domain / Title | Category | Deterministic Scope | Jules API Scope | Current Status |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **#4** | [Audit: CI Pipelines](https://github.com/HazemHassine/GitAudit/issues/4) | Audit | CI YAML linting via `actionlint`, Makefile integration | CI bottleneck, flakiness & parallelization analysis | **IN PROGRESS** |
| **#2** | [Audit: Build System](https://github.com/HazemHassine/GitAudit/issues/2) | Audit | Strict compiler flags, fail on warnings, bundle size limits | Build caching optimizations & multi-stage Dockerfile review | Open |
| **#3** | [Audit: Test Coverage & Quality](https://github.com/HazemHassine/GitAudit/issues/3) | Audit | Minimum coverage threshold enforcement (e.g. 80%) in CI | `AUTO_CREATE_PR` session to generate unit/integration tests | Open |
| **#5** | [Audit: Dependencies](https://github.com/HazemHassine/GitAudit/issues/5) | Audit | Dependabot/Renovate config for automated version updates & CVE alerts | Bloat identification, unused dependency removal, framework upgrades | Open |
| **#6** | [Audit: Security](https://github.com/HazemHassine/GitAudit/issues/6) | Audit | CodeQL/SAST scanning, dependency vulnerability alerts, secret scanning | Complex logic audit for auth flaws, race conditions, architecture | Open |
| **#7** | [Audit: Deployment Configuration](https://github.com/HazemHassine/GitAudit/issues/7) | Audit | Lint IaC manifests (`tflint`, `checkov`, `hadolint`) | Review deployment scripts for least-privilege IAM and HA tweaks | Open |
| **#8** | [Audit: Documentation](https://github.com/HazemHassine/GitAudit/issues/8) | Audit | Automated broken link checker, docstring enforcement via linters | Autogenerate OpenAPI specs, architectural overviews, usage examples | Open |
| **#9** | [Audit: Maintenance & Refactoring](https://github.com/HazemHassine/GitAudit/issues/9) | Audit | Strict code formatting (Black/Prettier) & cyclomatic complexity limits | Technical debt detection, modularization suggestions, refactoring PRs | Open |
| **#10** | [Feature: Active Health UI](https://github.com/HazemHassine/GitAudit/issues/10) | Feature | Embed dynamic CI/CD, coverage, and security badges in header/README | Lightweight non-blocking health dashboard component via GitHub API | Open |

---

## 🤖 Jules API: Deep Reference & Integration Guide

Multiple issues (#2 through #9) require invoking the **Google Labs Jules API**. Below is the complete technical reference required for any agent working with Jules.

### What is Jules?
Jules is an autonomous, asynchronous AI coding agent developed by Google Labs (powered by Gemini 3 Pro). Unlike copilot-style autocomplete extensions, Jules runs in an isolated cloud VM, clones the target repository, navigates the codebase, runs commands/tests, produces a diff or implementation plan, and can autonomously create pull requests.

### Authentication
- Requests require the HTTP header: `X-Goog-Api-Key: <JULES_API_KEY>`.
- API keys are generated at [jules.google.com/settings#api](https://jules.google.com/settings#api).
- In GitHub Actions workflows, the key MUST be referenced via repository secrets: `${{ secrets.JULES_API_KEY }}`.

### REST API Endpoints
Base URL: `https://jules.googleapis.com/v1alpha`

1. **Create a Coding Session** (`POST /v1alpha/sessions`):
   ```json
   {
     "prompt": "Task description and constraints for Jules",
     "sourceContext": {
       "source": "sources/github/HazemHassine/GitAudit",
       "githubRepoContext": {
         "startingBranch": "main"
       }
     },
     "automationMode": "AUTO_CREATE_PR",
     "requirePlanApproval": false
   }
   ```
   *Fields:*
   - `prompt`: String containing clear, measurable instructions and constraints.
   - `sourceContext.source`: The GitHub repository identifier in `sources/github/{owner}/{repo}` format.
   - `sourceContext.githubRepoContext.startingBranch`: Target base branch (e.g., `main`).
   - `automationMode`: Set to `"AUTO_CREATE_PR"` to have Jules automatically open a pull request when completed.
   - `requirePlanApproval`: If `true`, Jules pauses after generating a plan until approved via `:approvePlan`. If `false`, execution is autonomous.

2. **List Sessions** (`GET /v1alpha/sessions`):
   Retrieves history of sessions and their states (`QUEUED`, `IN_PROGRESS`, `COMPLETED`, `FAILED`).

3. **List Activities for a Session** (`GET /v1alpha/sessions/{sessionId}/activities`):
   Streams or inspects plan generation, command outputs, agent comments, and PR links.

4. **Approve a Plan** (`POST /v1alpha/sessions/{sessionId}:approvePlan`):
   Approves the generated plan when `requirePlanApproval` was set to `true`.

5. **Send Follow-up Message** (`POST /v1alpha/sessions/{sessionId}:sendMessage`):
   Sends additional feedback or follow-up instructions to an ongoing session.

### GitHub Action Integration: `google-labs-code/jules-invoke`
Google provides the composite GitHub Action [`google-labs-code/jules-invoke@v1`](https://github.com/google-labs-code/jules-invoke):
```yaml
- name: Invoke Jules
  uses: google-labs-code/jules-invoke@v1
  with:
    prompt: |
      Your task instructions here.
    jules_api_key: ${{ secrets.JULES_API_KEY }}
    starting_branch: main
    include_last_commit: false
    include_commit_log: true
```

### Security Considerations for Jules Workflows
- **Trigger Authorization**: For workflows triggered by GitHub issues or comments (`on: issues`), always enforce an allowlist check:
  ```yaml
  if: ${{ contains(fromJSON('["HazemHassine"]'), github.event.issue.user.login) }}
  ```
- **PR Guardrails**: Review Jules PRs before merging. Jules will branch and open a PR with its commits.

---

## 📋 Comprehensive Issue Details & Agent Runbooks

---

### Issue #4: Audit: CI Pipelines (ACTIVE BRANCH WORK)
**Status:** Implemented & Verified (Branch: `audit/issue-4-ci-pipelines`)

#### Objectives & Implementation
1. **Deterministic [COMPLETED]:**
   - Added `actionlint-py>=1.7.12,<2` to `apps/api/pyproject.toml` (dev dependencies).
   - Added `VENV_ACTIONLINT` and `lint-ci` target to `Makefile`.
   - Integrated `actionlint` into `make test` so all CI workflows are automatically linted during local and automated testing.
   - Added an explicit `Lint CI workflows` step to `.github/workflows/ci.yml`.
   - Verified that all repository workflows pass `actionlint` with 0 errors.
2. **Jules API [COMPLETED & VERIFIED]:**
   - Created `.github/workflows/jules-ci-analysis.yml` using `google-labs-code/jules-invoke@v1` triggered on CI failure or manual `workflow_dispatch`.
   - Created standalone executable CLI script `scripts/jules_ci_analysis.py` with `--dry-run`, `--focus`, `--include-ci-log`, and auto-loading of `.env`.
   - Dispatched and verified live test session `sessions/9916342744409535567` on `HazemHassine/GitAudit` via the Jules API (`https://jules.googleapis.com/v1alpha`).

#### Files Impacted
- `apps/api/pyproject.toml` (added `actionlint-py`)
- `Makefile` (added `lint-ci` target, integrated into `make test`)
- `.github/workflows/ci.yml` (added `Lint CI workflows` step)
- `.github/workflows/jules-ci-analysis.yml` (created Jules CI analysis workflow)
- `scripts/jules_ci_analysis.py` (created Python CLI for Jules CI analysis)
- `.env.example` (added `JULES_API_KEY` placeholder)

---

### Issue #2: Audit: Build System
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Next.js Web:
     - Enforce `typescript.tsconfigPath` strictness and verify zero compiler warnings in `apps/web/tsconfig.json` (`strict: true`, `noUncheckedIndexedAccess: true`).
     - Configure bundle size analysis using `@next/bundle-analyzer` and bundle budget thresholds.
   - Python API:
     - Verify wheel build via `hatchling` with strict flags, ensuring no packaging warnings.
   - Docker:
     - Ensure multi-stage builds in `apps/api/Dockerfile` and `apps/web/Dockerfile` leverage build caches effectively (e.g. `--mount=type=cache,target=/root/.cache/pip`).
2. **Jules API:**
   - Prompt Jules to review Dockerfile caching layers and build dependencies to optimize build time and reduce image sizes.

#### Agent Implementation Guidance
- Check `apps/web/package.json` scripts: `npm run build` and `npm run typecheck`.
- Check `apps/api/pyproject.toml` hatchling configuration.
- Check `apps/api/Dockerfile` and `apps/web/Dockerfile`.
- Jules prompt should inspect layers and advise on layer order (copying lockfiles first before application code).

---

### Issue #3: Audit: Test Coverage & Quality
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Add `pytest-cov` to `apps/api/pyproject.toml` dev dependencies.
   - Enforce an 80% coverage threshold: `pytest --cov=maintainer_api --cov-fail-under=80`.
   - Configure coverage reporting in CI (terminal output and XML/HTML report).
2. **Jules API:**
   - Trigger a Jules session with `automationMode: "AUTO_CREATE_PR"` to inspect untested branches in `apps/api/src/maintainer_api/` and generate test fixtures and assertions in `apps/api/tests/`.

#### Agent Implementation Guidance
- Currently, `apps/api/pyproject.toml` does not have `pytest-cov`. Add `pytest-cov>=5.0` to `[project.optional-dependencies] dev`.
- Inspect existing tests in `apps/api/tests/` (`test_api.py`, `test_service.py`, `test_curation.py`).
- Jules API prompt should emphasize: "Examine untested edge cases in maintainer_api/curation.py and maintainer_api/github.py. Add pytest unit tests without mocking internal logic unnecessarily."

---

### Issue #5: Audit: Dependencies
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Configure `.github/dependabot.yml` for:
     - GitHub Actions (`/`)
     - Python dependencies (`apps/api`)
     - Node.js dependencies (`apps/web`)
   - Schedule weekly updates and set pull-request limits.
2. **Jules API:**
   - Create a Jules audit workflow to detect unused dependencies (e.g. comparing installed packages against imports) and identify framework upgrade opportunities.

#### Agent Implementation Guidance
- Create `.github/dependabot.yml` with package ecosystems: `pip`, `npm`, `github-actions`.
- Run `npm audit` in `apps/web` and `pip audit` in `apps/api`.
- Jules prompt should look for dependency bloat and suggest lean alternatives.

---

### Issue #6: Audit: Security
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Add GitHub CodeQL analysis workflow (`.github/workflows/codeql.yml`) for `javascript-typescript` and `python`.
   - Integrate secret scanning pre-commit / CI check (e.g. `gitleaks` or `trufflehog`).
   - Run dependency vulnerability scanning in CI.
2. **Jules API:**
   - Audit complex logic (e.g., token handling in `maintainer_api/github.py`, prompt-injection boundary in `maintainer_api/curation.py`, command isolation in `maintainer_api/reproduction.py`) for authorization flaws and race conditions.

#### Agent Implementation Guidance
- Inspect `maintainer_api/reproduction.py` and verify Docker command sanitization.
- Inspect `maintainer_api/curation.py` for LLM prompt injection safeguards.
- Add `.github/workflows/codeql.yml` using GitHub's `github/codeql-action`.

---

### Issue #7: Audit: Deployment Configuration
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Lint `docker-compose.yml` and Dockerfiles with `hadolint` and `checkov`.
   - Ensure non-root users are configured in production containers.
   - Enforce environment variable validation and fail-fast configurations.
2. **Jules API:**
   - Review deployment scripts and Docker configurations for least-privilege security policies, graceful termination signals (`SIGTERM`), and horizontal auto-scaling recommendations.

#### Agent Implementation Guidance
- Check `docker-compose.yml` and both Dockerfiles.
- Ensure ports and volume mounts are properly isolated.
- Provide clear cloud-run or Kubernetes deployment manifests if planned for Milestone 7.

---

### Issue #8: Audit: Documentation
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Implement an automated broken link checker (e.g. `lychee` or markdown-link-check) in CI.
   - Enforce docstring presence and formatting using `ruff` rules (e.g., `D` rules in `pyproject.toml`).
2. **Jules API:**
   - Autogenerate and synchronize OpenAPI specification schemas (`openapi.json`).
   - Generate architectural overviews and comprehensive API usage examples.

#### Agent Implementation Guidance
- Configure `ruff` lint rule selections in `apps/api/pyproject.toml`: enable `D` (pydocstyle) or specific subsets.
- Write a script to dump OpenAPI schema directly from FastAPI:
  `python -c "import json; from maintainer_api.main import app; print(json.dumps(app.openapi()))" > docs/openapi.json`.

---

### Issue #9: Audit: Maintenance & Refactoring
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Enforce formatting and style checks:
     - Python: `ruff format --check` and `ruff check`.
     - Frontend: `prettier --check` and `eslint`.
   - Set cyclomatic complexity limits via `ruff` (`mccabe` / `C901` max-complexity = 10).
2. **Jules API:**
   - Identify technical debt, suggest modularization in `apps/api/src/maintainer_api/service.py` (which is currently >22KB and 500+ lines), and open refactoring PRs.

#### Agent Implementation Guidance
- `maintainer_api/service.py` contains coordinator logic, scoring logic, and database transactions.
- Refactor candidates: decompose into distinct service modules (e.g., `ScanCoordinatorService`, `RepositoryCatalogService`).

---

### Issue #10: Feature: Active Health UI
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Add dynamic CI/CD, coverage, and security badges to the project `README.md` and the UI header in `apps/web`.
2. **Task / Feature Implementation:**
   - Create a lightweight, non-blocking React component (`HealthDashboard.tsx`) in `apps/web/app/components/`.
   - Query GitHub API for repository workflow run statuses, commit statuses, and alert counts.
   - Use client-side caching (SWR/React Query pattern) or Next.js route handlers to prevent client-side bloat and rate-limit exhaustion.

#### Agent Implementation Guidance
- Review `apps/web/app/page.tsx` and `apps/web/app/components/`.
- Badges should link to GitHub Actions runs: `https://github.com/HazemHassine/GitAudit/actions/workflows/ci.yml/badge.svg`.
- Implement non-blocking skeleton states during data fetching.

---

## 🛠️ Contributing & Local Development Instructions

### Prerequisites
- Python 3.12+
- Node.js 20.19+
- Docker & Docker Compose

### Commands
```bash
# Set up virtual environment and dependencies
make install

# Run database migrations
make db-upgrade

# Run full test suite (pytest, ruff, eslint, typecheck)
make test

# Build frontend
make build

# Run end-to-end browser tests
make test-e2e
```
