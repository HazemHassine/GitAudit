# GitAudit Open Issues Master Guide & Tracker

This document provides a comprehensive tracking register, technical architectural specifications, and implementation guidance for all open issues in GitAudit. It is designed so that any AI agent or human contributor can understand what is required for each audit domain and immediately pick up any issue.

---

## 📌 Worker Registry

| Worker Name | Assigned Issue | Active Branch | Status | Assigned / Updated |
| :--- | :--- | :--- | :--- | :--- |
| **PipelineSentinel** | [Issue #4: Audit: CI Pipelines](https://github.com/HazemHassine/GitAudit/issues/4) | `audit/issue-4-ci-pipelines` | Implemented (Ready for Review) | 2026-09-10 02:08 |
| **CoverageSentinel** | [Issue #3: Audit: Test Coverage & Quality](https://github.com/HazemHassine/GitAudit/issues/3) | `audit/issue-3-test-coverage` | In Progress | 2026-09-10 02:10 |

---

## 🗺️ Issues Summary Matrix

| Issue ID | Domain / Title | Category | Deterministic Scope | Jules API Scope | UI & Jules Activity Scope | Current Status |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| **#4** | [Audit: CI Pipelines](https://github.com/HazemHassine/GitAudit/issues/4) | Audit | CI YAML linting via `actionlint`, Makefile integration | Shared CI review prompt | CI health card and shared Jules preview feed | Implemented (review pending) |
| **#2** | [Audit: Build System](https://github.com/HazemHassine/GitAudit/issues/2) | Audit | Strict compiler flags, bundle size limits, wheel and container policy checks | Shared build/caching review prompt | Build status card and shared Jules preview feed | Implemented (review pending) |
| **#3** | [Audit: Test Coverage & Quality](https://github.com/HazemHassine/GitAudit/issues/3) | Audit | 80% coverage gate and coverage report | Shared coverage-review prompt | Coverage meter and shared Jules preview feed | In progress; no live Jules session |
| **#5** | [Audit: Dependencies](https://github.com/HazemHassine/GitAudit/issues/5) | Audit | Dependabot and production dependency audits | Shared dependency-review prompt | Dependencies status card and shared Jules preview feed | Implemented (review pending) |
| **#6** | [Audit: Security](https://github.com/HazemHassine/GitAudit/issues/6) | Audit | CodeQL, secret scanning, dependency scans | Shared security-review prompt | Security status card and shared Jules preview feed | Implemented (review pending) |
| **#7** | [Audit: Deployment Configuration](https://github.com/HazemHassine/GitAudit/issues/7) | Audit | Compose, Dockerfile, and policy validation | Shared deployment-review prompt | Deployment status card and shared Jules preview feed | Implemented (review pending) |
| **#8** | [Audit: Documentation](https://github.com/HazemHassine/GitAudit/issues/8) | Audit | Broken-link checks and OpenAPI contract export | Shared documentation-review prompt | Documentation status card and shared Jules preview feed | In progress; docstring enforcement remains |
| **#9** | [Audit: Maintenance & Refactoring](https://github.com/HazemHassine/GitAudit/issues/9) | Audit | Formatting and complexity limits | Shared maintenance-review prompt | Maintenance status card and shared Jules preview feed | Open; complexity refactor remains |
| **#10** | [Feature: Active Health UI](https://github.com/HazemHassine/GitAudit/issues/10) | Feature | Audit dashboard and repository health cards | Shared control and activity feed | Modular dashboard for all eight audit areas | Implemented (review pending) |

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
    "requirePlanApproval": true
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

### GitAudit's unified interface
- The API exposes `GET` and `POST /api/v1/jules/sessions`. Every audit area uses the same session model, prompt definitions, statuses, and plan-approval guardrail.
- The dashboard's **Jules audit control** prepares previews only. It never invokes Jules from the browser; a preview shows the exact prompt and review targets.
- The manual-only `.github/workflows/jules-audit.yml` workflow accepts one audit area at a time. Its default is a preview; a live run needs an explicit `live` selection and the `JULES_API_KEY` secret.
- `scripts/jules_audit.py` shares the API prompt definitions. It is preview-first and requires `--live` for a network request.
- The activity feed lists sessions prepared through the current API process. It never fabricates remote activity, findings, or pull requests. No live Jules session has been created as part of this work.

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
2. **Jules API [PREVIEW-READY]:**
   - CI now uses the shared `build_jules_prompt("ci")` definition and unified session API instead of a bespoke automatic-on-failure workflow.
   - The manual `.github/workflows/jules-audit.yml` workflow and `scripts/jules_audit.py` are preview-first, require an explicit live request, and require plan approval before changes.
   - No live Jules session was dispatched during this work.
3. **UI Integration & Jules Activity Display:**
   - Embed a CI Pipelines status card/drawer in the UI dashboard displaying current workflow health, real-time Actionlint validation state, and active workflow run progress.
   - Surface live Jules CI analysis insights (bottlenecks identified, flakiness metrics, and suggested parallelization PR links).

#### Files Impacted
- `apps/api/pyproject.toml` (added `actionlint-py`)
- `Makefile` (added `lint-ci` target, integrated into `make test`)
- `.github/workflows/ci.yml` (added `Lint CI workflows` step)
- `.github/workflows/jules-audit.yml` (manual unified Jules review workflow)
- `scripts/jules_audit.py` (shared preview-first CLI)
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
3. **UI Integration & Jules Activity Display:**
   - Embed a Build Audit card in the central dashboard reflecting real-time check progress, compiler/bundle limit statuses, and displaying live Jules caching & Dockerfile recommendations with direct PR links.

#### Agent Implementation Guidance
- Check `apps/web/package.json` scripts: `npm run build` and `npm run typecheck`.
- Check `apps/api/pyproject.toml` hatchling configuration.
- Check `apps/api/Dockerfile` and `apps/web/Dockerfile`.
- Jules prompt should inspect layers and advise on layer order (copying lockfiles first before application code).
- UI: Implement `BuildAuditCard` component in `apps/web/app/components/` that slots into the main health dashboard grid.

---

### Issue #3: Audit: Test Coverage & Quality (ACTIVE BRANCH WORK)
**Status:** In Progress (Branch: `audit/issue-3-test-coverage`, Worker: `CoverageSentinel`)

#### Objectives
1. **Deterministic:**
   - Add `pytest-cov` to `apps/api/pyproject.toml` dev dependencies.
   - Enforce an 80% coverage threshold: `pytest --cov=maintainer_api --cov-fail-under=80`.
   - Configure coverage reporting in CI (terminal output and XML/HTML report).
2. **Jules API:**
   - Trigger a Jules session with `automationMode: "AUTO_CREATE_PR"` to inspect untested branches in `apps/api/src/maintainer_api/` and generate test fixtures and assertions in `apps/api/tests/`.
3. **UI Integration & Jules Activity Display:**
   - Embed a Test & Coverage card reflecting live test execution progress, current coverage meter vs threshold, and streaming Jules test-generation activity (plan status, untested edge cases identified, generated test PRs).

#### Agent Implementation Guidance
- Currently, `apps/api/pyproject.toml` does not have `pytest-cov`. Add `pytest-cov>=5.0` to `[project.optional-dependencies] dev`.
- Inspect existing tests in `apps/api/tests/` (`test_api.py`, `test_service.py`, `test_curation.py`).
- Jules API prompt should emphasize: "Examine untested edge cases in maintainer_api/curation.py and maintainer_api/github.py. Add pytest unit tests without mocking internal logic unnecessarily."
- UI: Implement `CoverageAuditCard` component in `apps/web/app/components/` that renders a dynamic coverage gauge and links to Jules-generated PRs.

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
3. **UI Integration & Jules Activity Display:**
   - Embed a Dependencies Audit card reflecting live audit progress, vulnerability alerts, and showing Jules dependency bloat analysis, unused package removals, and upgrade suggestions.

#### Agent Implementation Guidance
- Create `.github/dependabot.yml` with package ecosystems: `pip`, `npm`, `github-actions`.
- Run `npm audit` in `apps/web` and `pip audit` in `apps/api`.
- Jules prompt should look for dependency bloat and suggest lean alternatives.
- UI: Implement `DependenciesAuditCard` component displaying CVE badges and Jules upgrade PR recommendations.

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
3. **UI Integration & Jules Activity Display:**
   - Embed a Security Audit card showing active security scan status, alert counters, and surfacing Jules deep-audit findings (authorization flaws, concurrency risks, remediation suggestions).

#### Agent Implementation Guidance
- Inspect `maintainer_api/reproduction.py` and verify Docker command sanitization.
- Inspect `maintainer_api/curation.py` for LLM prompt injection safeguards.
- Add `.github/workflows/codeql.yml` using GitHub's `github/codeql-action`.
- UI: Implement `SecurityAuditCard` with an active scanner heartbeat and Jules vulnerability report pane.

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
3. **UI Integration & Jules Activity Display:**
   - Embed a Deployment Audit card showing IaC manifest validation state, real-time check indicator, and displaying Jules recommendations for least-privilege IAM and high-availability configuration.

#### Agent Implementation Guidance
- Check `docker-compose.yml` and both Dockerfiles.
- Ensure ports and volume mounts are properly isolated.
- Provide clear cloud-run or Kubernetes deployment manifests if planned for Milestone 7.
- UI: Implement `DeploymentAuditCard` showing container configuration health and Jules IAM optimization tips.

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
3. **UI Integration & Jules Activity Display:**
   - Embed a Documentation Audit card displaying docstring coverage metrics, broken link check progress, and Jules autogenerated OpenAPI/architecture documentation previews.

#### Agent Implementation Guidance
- Configure `ruff` lint rule selections in `apps/api/pyproject.toml`: enable `D` (pydocstyle) or specific subsets.
- Write a script to dump OpenAPI schema directly from FastAPI:
  `python -c "import json; from maintainer_api.main import app; print(json.dumps(app.openapi()))" > docs/openapi.json`.
- UI: Implement `DocumentationAuditCard` rendering doc completeness progress and a preview modal for Jules-generated API specs.

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
3. **UI Integration & Jules Activity Display:**
   - Embed a Maintenance & Refactoring card showing code style status, complexity hotspots, and displaying Jules refactoring recommendations, modularization plans, and PR links.

#### Agent Implementation Guidance
- `maintainer_api/service.py` contains coordinator logic, scoring logic, and database transactions.
- Refactor candidates: decompose into distinct service modules (e.g., `ScanCoordinatorService`, `RepositoryCatalogService`).
- UI: Implement `RefactoringAuditCard` rendering complexity warnings and an active feed of Jules refactoring PRs.

---

### Issue #10: Feature: Active Health UI
**Status:** Open

#### Objectives
1. **Deterministic:**
   - Add dynamic CI/CD, coverage, and security badges to the project `README.md` and the UI header in `apps/web`.
2. **Task / Modular Architecture:**
   - Create the central command-center layout in `apps/web/app/components/HealthDashboard.tsx` with a responsive modular grid providing dedicated slots for all audit cards (Build, Tests, CI, Deps, Security, Deployment, Docs, Refactoring).
   - Fetch audit statuses asynchronously via the GitHub API and backend endpoints to avoid client-side blocking.
3. **Live Progress & Jules Activity Feed:**
   - Include visual spinners/pulsing indicators when an audit check is actively running.
   - Embed a global **Jules Agent Activity Feed** that streams ongoing Jules sessions, current steps/activities, and generated PRs across all audit areas.

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
