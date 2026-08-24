# OSS Maintainer

An evidence-first, read-only operations console for observing explicitly authorized GitHub
repositories. It automatically inventories every repository visible to the configured GitHub App
installation or fine-grained token, persists scan attempts and evidence, and makes health scoring
auditable.

Milestone 1 does not execute repository code or make GitHub changes.

## What it does now

- Discovers all authorized repositories and monitors them automatically.
- Scans unscanned or stale repositories when the API starts, with bounded concurrency.
- Evaluates CI/check results against the exact default-branch commit being reported.
- Keeps completed, partial, and failed scan attempts as durable history.
- Separates evidence quality from evidence coverage so missing CI cannot appear healthy.
- Shows repository permalinks, scan comparisons, raw source evidence, freshness, and rule ledgers.
- Keeps the last persisted inventory usable during a GitHub outage.
- Supports GitHub App installation authentication and a local fine-grained-token fallback.

Explicitly stopping monitoring retains history and prevents later automatic inventory runs from
re-enabling that repository. Reconnecting it makes it eligible for automatic scans again.

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

3. Install and run:

   ```bash
   docker compose up -d db
   make install
   make dev
   ```

`make dev` applies database migrations and runs the API and web app together. The web UI is at
`http://localhost:3000`; the API and OpenAPI documentation are at `http://localhost:8001` and
`http://localhost:8001/docs`.

PostgreSQL is published on host port `5433` by default. Override it with
`POSTGRES_HOST_PORT` and keep `DATABASE_URL` aligned when running the API on the host.

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
