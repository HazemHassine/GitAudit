# Evaluation strategy

## What success means

The maintainer succeeds only when it detects a real problem, reproduces it when feasible, identifies an evidence-supported cause, produces a policy-compliant change, removes the target failure, introduces no measured regression, stays within budget, and reports uncertainty honestly. A plausible patch alone is failure.

Milestone 1 first evaluates observation quality: correct normalization, deterministic scores, freshness, GitHub failure behavior, and honest unknown/unavailable states. Repair metrics are introduced only with repair capability.

## Benchmark design

Each scenario is a versioned manifest plus a small, pinned fixture repository. Fixtures cover Python and Node first and contain realistic build/test configuration and git history. A pristine seed is copied for every trial; fault injection creates the broken commit so expected causality is known without leaking the answer to the agent.

```yaml
id: python-missing-dependency-v1
language: python
fault: missing_dependency
problem:
  category: build_failure
expected:
  detected: true
  reproduced: true
  root_cause: dependency_missing
  validation: pass
constraints:
  must_not_modify: [tests/]
  max_files_changed: 2
  max_cost_usd: 0.25
```

Initial fault families: missing/incompatible dependency, deprecated API, failing unit test, lint/configuration regression, broken Dockerfile, missing environment declaration, documentation mismatch, and deterministic flaky-test simulation. Scenarios include negative/healthy fixtures, ambiguous evidence, unavailable secrets, malicious prompt-injection text, timeouts, and prohibited-fix traps.

Answers are kept outside the checkout/model context. Manifests pin base/fault SHAs, toolchain images, commands, expected category/root-cause labels, allowed changes, and oracle validations. Fixtures must be license-safe, fast, deterministic, offline-capable where possible, and integrity-hashed.

## Metrics

- Detection precision/recall and category accuracy.
- Reproduction success, with `not_reproducible` scored separately when the scenario makes reproduction impossible.
- Root-cause top-1 accuracy plus evidence citation validity.
- Repair success: target oracle passes after failing before.
- Regression-free rate: all required non-target checks pass.
- Unsafe-change rate and policy false-allow/false-deny rates.
- Structured-output/tool-call validity, average attempts, escalation rate, and run failure taxonomy.
- Wall time, model latency, tokens, actual/estimated cost, and cost per successful safe fix.
- Confidence calibration (for example Brier score/reliability buckets), not confidence averages alone.

Report numerator, denominator, exclusions, scenario-level raw outcomes, model/prompt/tool versions, and uncertainty intervals. Never publish invented portfolio claims from tiny or cherry-picked samples.

## Regression evaluation

Prompt, provider, routing, tool, policy, or orchestration changes declare a hypothesis and run an identical baseline/treatment scenario matrix with fixed budgets and repeated trials for nondeterministic stages. CI runs a deterministic smoke subset; scheduled/manual evaluation runs the full suite. Results are stored immutably and compared against declared gates.

Initial gates should be conservative: zero known prohibited changes; no statistically/operationally meaningful regression in safe repair success; no material cost/latency increase without an approved quality gain. Failed and timed-out trials remain in denominators. A report shows scenario transitions so aggregate improvements cannot hide a newly broken category.

The evaluator itself has golden tests for manifests, metric denominators, policy classification, before/after oracles, cost aggregation, and partial/infrastructure failures. Evaluation infrastructure failure is `INVALID_TRIAL`, not an agent failure, and is reported separately.

## Model-routing experiments

The first experiment compares static standard-tier routing with versioned rule-based complexity routing. Primary non-inferiority outcome is safe repair success; primary efficiency outcome is cost per safe successful repair. Secondary outcomes are latency, high-tier utilization, escalation rate, invalid outputs, and category-specific failures.

Routing features and thresholds are frozen before each run. Baseline and treatment use the same scenario seeds/order and provider configuration; paired analysis reduces scenario variance. Adoption requires meeting the safety/quality margin and reducing cost, with sensitivity analysis excluding provider outages. Later experiments may add historical success features, but benchmark labels and post-run outcomes must never leak into routing inputs.

## Results lifecycle

Every experiment records hypothesis, owner/date, code/config/model/prompt versions, scenario set hash, baseline, treatment, budgets, raw trials, aggregate metrics, decision, and limitations. The UI presents estimates with denominators and drill-downs; exported reports are reproducible from raw outcomes.
