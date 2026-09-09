# GitAudit

An evidence-first AI curator for a developer's authorized GitHub repositories. It inventories the
repositories visible to a configured GitHub App or fine-grained token, persists health evidence,
and uses a bounded LangGraph workflow to propose improvements to profile metadata and
documentation.

Milestone 2 does not execute repository code, fix source code, or make GitHub changes. AI output is
stored as a reviewable proposal, never treated as observed evidence or applied automatically.

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

## Milestone 2 safety boundary

Repository descriptions, topics, README text, and scan output are treated as untrusted input. The
LangGraph workflow runs a deterministic pre-check before requesting a strict structured assessment.
There are intentionally no API routes for approving or applying a proposal, changing metadata,
editing a README, adding CI, or archiving a repository yet.
