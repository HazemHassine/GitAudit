# GitAudit

[![CI](https://github.com/HazemHassine/GitAudit/actions/workflows/ci.yml/badge.svg)](https://github.com/HazemHassine/GitAudit/actions/workflows/ci.yml)
[![Security](https://github.com/HazemHassine/GitAudit/actions/workflows/security.yml/badge.svg)](https://github.com/HazemHassine/GitAudit/actions/workflows/security.yml)
[![Docs](https://github.com/HazemHassine/GitAudit/actions/workflows/docs.yml/badge.svg)](https://github.com/HazemHassine/GitAudit/actions/workflows/docs.yml)

An evidence-first AI curator for a developer's authorized GitHub repositories. It inventories the
repositories visible to a configured GitHub App or fine-grained token, persists health evidence,
and uses a bounded LangGraph workflow to propose improvements to profile metadata and
documentation.

Profile-curation output is stored as a reviewable proposal, never treated as observed evidence or
applied automatically. The consolidated audit-and-repair workflow described below is planned;
it has not been implemented yet.

## What it does now

- Discovers all authorized repositories and monitors them automatically.
- Scans unscanned or stale repositories when the API starts, with bounded concurrency.
- Evaluates CI/check results against the exact default-branch commit being reported.
- Keeps completed, partial, and failed scan attempts as durable history.
- Separates evidence quality from evidence coverage so missing CI cannot appear healthy.
- Shows repository permalinks, scan comparisons, raw source evidence, freshness, and rule ledgers.
- Keeps the last persisted inventory usable during a GitHub outage.
- Supports GitHub App installation authentication and a local fine-grained-token fallback.
- Classifies repository positioning while preserving uncertainty.
- Proposes missing descriptions, topics, README improvements, and CI follow-up.
- Persists every AI assessment with its model, prompt version, commit SHA, evidence, and status.
- Provides local coverage and CI audit evidence, with unavailable results for remote repositories
  when local evidence does not apply.
- Prepares Jules review previews from the dashboard; current Jules history is process-local.
- Includes a legacy reproduction runner and explicit live Jules launch paths. These do not yet
  provide the durable execution, shared quota, or one-PR guarantees in the planned workflow.

Explicitly stopping monitoring retains history and prevents later automatic inventory runs from
re-enabling that repository. Reconnecting it makes it eligible for automatic scans again.

## Planned audit workflow

A dedicated **Audits** page will let you select repositories, remember that selection, and start
one run with **Run checks**. Each repository will receive a report tied to its default-branch
commit. Healthy repositories will consume no Jules session and produce no empty PR; deeper AI
review will be optional.

For actionable findings, GitAudit will prepare one Jules repair plan per repository, require your
approval of the actual plan version, independently validate the resulting patch, and create or
update one tracked PR titled **`GitAudit: Repository check — <repository>`**. You will review and
merge it. Repairs will focus on evidenced failures, vulnerabilities, relevant tests, and small
documentation or configuration corrections.

The implementation is organized into five milestones:

1. **Durable, safe execution:** PostgreSQL-backed jobs, renewable worker leases, durable events,
   single-owner authentication, pause/resume/stop controls, and replacement of the legacy runner
   with disposable Docker execution without host fallback.
2. **Real repository audits:** Python and JavaScript/TypeScript adapters, repository-specific
   checks, evidence and caching, and live reports at `/audits` and `/audits/runs/{id}`. Missing,
   unsupported, and unavailable checks will remain visible.
3. **Jules orchestration:** source discovery, persisted plans and activities, version-specific
   approval, and a central limit of 80 new sessions per rolling 24 hours. Initial concurrency
   will be two local check jobs and three active Jules planning/execution slots.
4. **Consolidated repairs:** patch source/base verification, independent validation, at most two
   correction rounds in the same session, and one tracked open PR per repository. Subsequent
   approved runs will update that PR, with human changes requiring reconciliation.
5. **Finish and prove:** accessible progress views, reconnect/replay, restart recovery, operational
   documentation, and offline Python, Node, and monorepo scenarios with mocked providers.

FastAPI, Next.js, and PostgreSQL will remain the stack, with a separate worker and local Docker
Compose deployment. Checks will use each repository's own rules. Dependency installation will
have controlled network access; test/build containers will have networking disabled by default
and receive neither provider credentials nor the Docker socket.

Development verification will use offline provider fixtures. A separately authorized pilot on
one disposable repository, capped at two live Jules sessions, is required before claiming the
full repair workflow works. It must demonstrate approval, patch retrieval, independent
validation, PR creation, and an update to that same PR.

## Layout

- `apps/api` — FastAPI modular monolith, scanner, scorer, GitHub adapter, and migrations
- `apps/web` — Next.js command center, repository reports, and connection settings
- `docs` — architecture, product, roadmap, and evaluation strategy

## Local development

Requirements are Python 3.12+, Node 20.19+, and Docker.

1. Create local configuration:

   ```bash
   cp .env.example .env
   ```

2. Add a read-only GitHub connection to `.env`.

   For local development, create a fine-grained token restricted to the repositories you want the
   app to see, grant read access to Metadata, Contents, Actions, and Checks, then set:

   ```dotenv
   GITHUB_AUTH_MODE=token
   GITHUB_TOKEN=github_pat_...
   ```

   For a GitHub App installation, use:

   ```dotenv
   GITHUB_AUTH_MODE=app
   GITHUB_APP_ID=...
   GITHUB_INSTALLATION_ID=...
   GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/private-key.pem
   GITHUB_APP_SLUG=your-app-slug
   ```

3. Add the OpenAI key used by the profile-curation graph:

   ```dotenv
   OPENAI_API_KEY=sk-proj-...
   OPENAI_MODEL=gpt-5.4-mini
   ```

4. Run the full application with Docker:

   ```bash
   docker compose up --build -d
   ```

   To view logs:
   ```bash
   docker compose logs -f
   ```

   To stop all services:
   ```bash
   docker compose down
   ```

The web UI is at `http://localhost:3000`; the API and OpenAPI documentation are at `http://localhost:8001` and `http://localhost:8001/docs`.

*(Optional local development on the host without Docker: `make install && make dev`)*

## Automatic inventory

`AUTO_SCAN_ON_STARTUP=true` is the default. On API startup the coordinator:

1. reads every repository authorized by the GitHub App installation or token;
2. persists newly discovered repositories;
3. scans every unscanned, previously failed, or stale active repository; and
4. exposes batch progress at `GET /api/v1/sync`.

Use `SCAN_STALE_AFTER_MINUTES`, `MAX_CONCURRENT_SCANS`, and
`AUTO_SCAN_INTERVAL_MINUTES` to tune the behavior. An interval of `0` disables recurring scans
while retaining startup and manual full-inventory scans.

## Verification

```bash
make test       # API unit/integration tests, Ruff, ESLint, and TypeScript
make build      # production Next.js build
make test-e2e   # Playwright browser happy path
```

The API exposes `/healthz` for liveness, `/readyz` for database readiness, and `/metrics` for
Prometheus-compatible request and scan metrics. Logs are structured JSON and carry request IDs.

## Current execution boundaries

Repository descriptions, topics, README text, and scan output are treated as untrusted input. The
LangGraph workflow runs a deterministic pre-check before requesting a strict structured assessment.
There are intentionally no API routes for approving or applying a proposal, changing metadata,
editing a README, adding CI, or archiving a repository yet.

These profile-curation boundaries do not describe the legacy reproduction runner or live Jules
launch paths. The current live Jules adapter enables provider PR creation, and its session history
is not durable. The planned worker, centralized budget, and GitAudit-owned publication lifecycle
must replace those paths before the new audit workflow can offer its stated guarantees.
