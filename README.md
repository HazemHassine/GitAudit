# OSS Maintainer

An evidence-first operations console for monitoring and, in later milestones, safely maintaining explicitly authorized GitHub repositories.

The current scaffold is intentionally limited to Milestone 1: read-only repository visibility, normalized health signals, deterministic explainable scoring, scan history contracts, and a command-center UI. It does not execute repository code or make GitHub changes.

## Layout

- `apps/api` — FastAPI modular monolith and health-scoring domain
- `apps/web` — Next.js operations console
- `docs` — architecture, product, roadmap, and evaluation strategy

## Local development

Requirements are Python 3.12+, Node 20.19+, and Docker. This machine currently has Python 3.11 and Node 20.12, so use containers or install the required runtimes locally.

```bash
cp .env.example .env
docker compose up -d db
make install
make dev
```

PostgreSQL is published on host port `5433` by default to avoid collisions with a locally installed PostgreSQL server. Override it with `POSTGRES_HOST_PORT`; keep `DATABASE_URL` aligned with that value when running the API on the host.

Run checks with `make test`. The current Milestone 1 flow reads the authenticated GitHub account, lists repositories accessible to the fine-grained token, lets you explicitly monitor a repository, persists it, and creates evidence-backed scans from default-branch commits, GitHub Actions history, and README presence. The web UI runs on `http://localhost:3000`; the API and its OpenAPI documentation run on port `8001`.
