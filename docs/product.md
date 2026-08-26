# Product definition

## Product promise

GitAudit is an evidence-first GitHub profile curator and reliability console for one developer's explicitly authorized repositories. It makes repository health legible, proposes metadata and documentation maintenance, later investigates concrete problems, and asks for review whenever evidence or policy is insufficient.

## Information architecture

Primary navigation is **Command Center**, **Repositories**, **Problems**, **Runs**, **Reports**, **Experiments**, and **Settings**. Repositories, problems, runs, evidence, and evaluations are stable resources with shareable URLs; chat is not a navigation primitive.

Milestone 1 implements Command Center, Repositories, repository detail, scan reports, and GitHub settings. Milestone 2 adds persisted AI curation assessments and proposal review. Empty future sections should not imply capabilities exist.

## Primary journeys

1. **Onboard:** install the GitHub App, select its authorized repositories, confirm read-only permissions, and land on an automatically scanned inventory. Repositories explicitly excluded in the console retain history and stay excluded from later syncs.
2. **Understand health:** open a repository, read status and freshness, separate build/CI from deployment, expand a dimension to see deterministic rules and source evidence, and compare historical snapshots.
3. **Curate a profile (M2+):** review repository relevance, confidence, strengths, concerns, and proposed descriptions, topics, README plans, CI follow-up, or archive review. No proposal is applied in M2.
4. **Investigate (M3+):** select a detected problem, start a bounded run, follow live structured events, inspect reproduction and evidence, pause/stop, and receive a durable report.
5. **Review a fix (M5+):** compare before/after validation, inspect diff/risk/policy/remaining uncertainty, then approve PR creation or reject/request deeper investigation.
6. **Improve the maintainer (M6+):** create a versioned experiment, run identical scenarios for baseline/treatment, inspect failures and confidence intervals, and adopt or reject the change.

## State semantics

Repository status is derived from the latest non-stale scan: `UNSCANNED`, `SCANNING`, `HEALTHY`, `ATTENTION`, `DEGRADED`, or `SCAN_FAILED`. Signal status is independently `PASS`, `FAIL`, `UNKNOWN`, or `UNAVAILABLE`. `UNKNOWN` means no observation/configuration; `UNAVAILABLE` means an attempted source could not answer. Both show cause and timestamp.

Problem lifecycle: `DETECTED → INVESTIGATING → REPRODUCED → DIAGNOSED → FIXING → VALIDATING → EVALUATING → READY_FOR_REVIEW → PR_CREATED → RESOLVED`, with terminal/side outcomes `BLOCKED`, `NEEDS_HUMAN`, `UNSAFE_TO_AUTOFIX`, `FAILED`, and `DISMISSED`.

Run phases are `QUEUED`, `COLLECTING_EVIDENCE`, `REPRODUCING`, `DIAGNOSING`, `PLANNING`, `IMPLEMENTING`, `VALIDATING`, `EVALUATING`, `AWAITING_APPROVAL`, `CREATING_PR`, and terminal `COMPLETED`, `STOPPED`, or `FAILED`. A run status and problem status are distinct: a failed attempt does not erase the problem.

## Command Center and visual language

The command center answers in order: Is the maintainer active? What changed? Which repository needs attention? Is an investigation live? What requires me? A dense repository pulse table, prioritized attention queue, and one active trace replace a grid of generic cards.

The visual grammar uses five labeled layers: **PULSE** (observed health), **TRACE** (agent activity), **EVIDENCE** (immutable observations), **ACTION** (proposed/performed mutation), and **VERIFY** (before/after proof). Color is redundant with icons/text; motion is reserved for currently active phases and new events; reduced-motion preferences are honored.

Repository detail begins with identity, freshness, default SHA, last CI/deployment observation, and health trend. Dimensions are compact rows with score/status and observation freshness. Expansion shows the rule ledger, not a generated explanation. Deployment remains `UNKNOWN` until configured or observed.

Overall score describes the quality of observed evidence; evidence coverage is shown separately.
Missing required CI evidence gates repository status to `ATTENTION`, even when the available
evidence scores perfectly. CI evidence must refer to the exact default-branch SHA recorded by the
scan.

## Transparency model

Expose phase, concise engineering hypotheses, evidence, files inspected, sanitized tool/command summaries, planned actions, diffs, validations, model/routing rationale, tokens/cost/latency/retries, confidence, risk/policy decision, rollback information, and final uncertainty. Do not expose hidden chain-of-thought, raw secrets, credentials, or unfiltered logs. Every summary links to its source artifact and collection time.

Health pages display scoring version and contributions. Run timelines are append-only events with summary-first expansion. Estimated cost is labeled until provider usage settles; unavailable actual cost stays unavailable.

## Notifications

Notifications are state-change driven and deduplicated. A daily digest summarizes checked/healthy/attention repositories and completed actions. Immediate incident email is reserved for configurable severity/status transitions; fix-ready email includes validation, risk, and PR/review link. Repeated unchanged scans are silent. Users can set quiet hours and per-repository channels later; failures to send never change repository truth.
