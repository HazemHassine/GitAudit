"use client";

import { AuditStatusCard } from "./AuditStatusCard";
import CoverageCard from "./CoverageCard";
import { CiPipelinesAuditCard } from "./CiPipelinesAuditCard";
import { JulesActivityFeed } from "./JulesActivityFeed";

export function HealthDashboard() {
  return (
    <section className="healthDashboard" aria-label="Repository audit health dashboard">
      <div className="healthDashboardHead">
        <div>
          <p className="label">AUDIT HEALTH DASHBOARD</p>
          <h2>Checks, evidence, and automation status</h2>
        </div>
        <span>Local evidence is labelled separately from repository telemetry.</span>
      </div>
      <JulesActivityFeed />
      <div className="auditCardGrid">
        <AuditStatusCard issue={2} title="Build system" status="configured" summary="Strict TypeScript, compressed bundle budgets, and API wheel validation are wired into CI." checks={["noUncheckedIndexedAccess", "gzip bundle budgets", "wheel integrity"]} command="make build" />
        <CoverageCard />
        <CiPipelinesAuditCard />
        <AuditStatusCard issue={5} title="Dependencies" status="configured" summary="Weekly Dependabot updates and production npm/pip audits are wired into CI." checks={["Dependabot", "npm audit", "pip audit"]} command="npm --prefix apps/web audit --omit=dev" />
        <AuditStatusCard issue={6} title="Security" status="configured" summary="CodeQL, secret scanning, and production dependency auditing run in the security workflow." checks={["CodeQL", "gitleaks", "dependency scanning"]} command=".github/workflows/security.yml" />
        <AuditStatusCard issue={7} title="Deployment configuration" status="configured" summary="Compose validation and container policy checks are wired into CI; detailed run telemetry is not persisted yet." checks={["non-root containers", "Hadolint", "Checkov"]} command="make validate-compose" />
        <AuditStatusCard issue={8} title="Documentation" status="configured" summary="Markdown links and the generated OpenAPI contract are checked in CI; docstring enforcement remains a tracked follow-up." checks={["link validation", "OpenAPI export", "docstring follow-up"]} command="python scripts/export_openapi.py --check" />
        <AuditStatusCard issue={9} title="Maintenance & refactoring" status="planned" summary="Formatting, complexity telemetry, and debt recommendations are pending." checks={["formatting", "complexity", "refactoring recommendations"]} />
      </div>
    </section>
  );
}
