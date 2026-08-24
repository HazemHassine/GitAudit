# Roadmap

Each slice must be demoable, observable, tested, and honest about unavailable data. Later milestones begin only after the preceding completion criteria hold.

## M1 — Repository visibility

**Goal:** establish trustworthy, read-only repository health snapshots.

**User-visible outcome:** connect one authorized repository, trigger a scan, see metadata/CI state, inspect every scoring contribution, and compare scan history.

**Slices**

1. Foundation: local Postgres, typed configuration, migrations, structured logs, health endpoint, Next.js shell.
2. Repository inventory: GitHub App installation/repository authorization, automatic metadata sync, repository list/detail, and retained-history exclusion.
3. Scan: exact default-branch SHA checks, recent Actions runs, normalized partial/failure signals, and persisted scan attempts.
4. Explainability: versioned scoring rules, evidence drawer, health dimensions, and report history.

**Backend:** domain models, SQLAlchemy repositories, GitHub port/adapter, scanner, scorer, REST resources, error/rate-limit behavior. **Frontend:** command-center shell, inventory, detail, score breakdown, scan history, clear unknown/unavailable states. **Tests:** scorer unit/property cases, GitHub contract fixtures, persistence integration tests, API tests, and one browser happy path. **Complete when:** a fresh setup can authorize and automatically scan every installation repository; reruns retain history; every point has a rule/evidence reference; no GitHub write permission is requested; telemetry identifies scan failures.

## M2 — Reproduction engine

**Goal:** reproduce a selected failed Actions job at its exact commit in an isolated workspace.

**User-visible outcome:** click Investigate and watch checkout, sandbox preparation, and reproduction events; inspect command, exit code, artifacts, and limitations.

**Backend:** problem/evidence/run-event records, CI log retrieval, project detection for Python/Node, Docker sandbox port, bounded command runner, SSE, cancellation, artifact retention. **Frontend:** problem and run pages, live phase timeline, expandable evidence, stop action. **Tests:** malicious fixture threat cases, resource/time limits, adapter contracts, reconnecting SSE, deterministic failed-build fixture. **Complete when:** the reference CI failure is reproduced from the recorded SHA without host execution or secret exposure and cleanup occurs on success/failure/cancel.

## M3 — Evidence-first diagnosis

**Goal:** turn reproduced failures into typed, auditable diagnoses without changing code.

**User-visible outcome:** a diagnosis report presents ranked concise hypotheses, supporting/contradicting evidence, confidence, selected model tier, cost, and uncertainty.

**Backend:** checkpointed LangGraph-style workflow, prompt/version registry, structured-output validation, provider abstraction, routing v1, budgets/escalation, injection-resistant context builder. **Frontend:** diagnosis view, model-decision event, cost/budget, deeper-investigation action. **Tests:** node tests, invalid-output/retry cases, prompt-injection fixtures, provider fakes, diagnosis benchmark. **Complete when:** benchmark diagnoses are reproducible, schema-valid, evidence-linked, budget-bounded, and baseline metrics are published.

## M4 — Safe autonomous repair

**Goal:** produce a validated patch and, only after user approval, a PR.

**User-visible outcome:** review before/after results, diff, policy/risk decision, uncertainties, and approve PR creation.

**Backend:** isolated mutable worktree, constrained editing tools, validation planner, bounded repair loop, deterministic risk/autonomy policy, stale-SHA check, GitHub branch/commit/PR writes with idempotency. **Frontend:** fix review, diff/evidence/validation panes, approve/reject/retry controls. **Tests:** policy matrices, stale-base/concurrency, regression fixtures, GitHub write contracts, end-to-end repair. **Complete when:** low-risk fixtures produce regression-free patches; prohibited changes are blocked; no default-branch write/merge exists; PR creation requires approval.

## M5 — Evaluation laboratory

**Goal:** make maintainer changes measurable and regression-gated.

**User-visible outcome:** compare named experiments and baseline/treatment results across quality, safety, cost, and latency.

**Backend:** scenario manifests, fixture lifecycle/fault injection, evaluator, repeated trials, immutable experiment results, CI comparison gate. **Frontend:** experiments list/detail, metric intervals, failure drill-down. **Tests:** evaluator self-tests, fixture integrity, metric calculations, CI smoke suite. **Complete when:** a versioned benchmark runs locally and in CI, publishes raw outcomes, and prevents agreed safety/quality regressions.

## M6 — Productionization

**Goal:** operate scheduled scans and recoverable runs reliably.

**User-visible outcome:** scheduled monitoring, resumable work, useful daily/incident/fix-ready email, and budget controls.

**Backend:** durable lightweight queue/worker, leases/idempotency/recovery, OpenTelemetry export, email abstraction, retention, Cloud Run deployment and CI/CD. **Frontend:** schedules, notification/budget settings, failure/retry state. **Tests:** crash recovery, duplicate delivery, provider outage/backoff, deployment smoke and migration tests. **Complete when:** staged operation survives restarts and transient outages, alerts are actionable, and dashboards expose SLOs/cost.

## M7 — Advanced intelligence

**Goal:** improve coverage and routing using measured evidence.

**User-visible outcome:** deployment targets, dependency maintenance, flaky-test trends, and explainable routing experiments.

**Backend:** HTTP deployment checks, dependency and flake detectors, richer adapters, learned/calibrated routing while retaining policy bounds. **Frontend:** build-versus-deployment distinction, trends, routing analytics. **Tests:** detector precision/recall sets, routing experiments, provider fallback and calibration. **Complete when:** each capability beats its declared baseline without violating safety/cost gates.
