"use client";

import { AuditStatusCard } from "./AuditStatusCard";
import CoverageCard from "./CoverageCard";
import { CiPipelinesAuditCard } from "./CiPipelinesAuditCard";

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
      <div className="auditCardGrid">
        <AuditStatusCard issue={2} title="Build system" status="configured" summary="Strict TypeScript, compressed bundle budgets, and API wheel validation are wired into CI." checks={["noUncheckedIndexedAccess", "gzip bundle budgets", "wheel integrity"]} command="make build" />
        <CoverageCard />
        <CiPipelinesAuditCard />
        <AuditStatusCard issue={5} title="Dependencies" status="planned" summary="Dependency update policy and vulnerability reporting are not configured yet." checks={["Dependabot", "npm audit", "pip audit"]} />
        <AuditStatusCard issue={6} title="Security" status="planned" summary="CodeQL, secret scanning, and dependency scanning are pending." checks={["CodeQL", "secret scanning", "vulnerability scanning"]} />
        <AuditStatusCard issue={7} title="Deployment configuration" status="configured" summary="Compose validation and container policy checks are wired into CI; detailed run telemetry is not persisted yet." checks={["non-root containers", "Hadolint", "Checkov"]} command="make validate-compose" />
        <AuditStatusCard issue={8} title="Documentation" status="planned" summary="Broken-link checks, OpenAPI export, and documentation telemetry are pending." checks={["link validation", "OpenAPI export", "docstrings"]} />
        <AuditStatusCard issue={9} title="Maintenance & refactoring" status="planned" summary="Formatting, complexity telemetry, and debt recommendations are pending." checks={["formatting", "complexity", "refactoring recommendations"]} />
      </div>
    </section>
  );
}
