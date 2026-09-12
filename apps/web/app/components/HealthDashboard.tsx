"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { request } from "../lib/api";
import type { AuditSnapshot } from "../lib/audit-types";

export function HealthDashboard({ repositoryId }: { repositoryId?: string }) {
  const [runs, setRuns] = useState<AuditSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    request<AuditSnapshot[]>("/api/v1/audits/runs").then(items => setRuns(repositoryId ? items.filter(run => run.repositories.some(repo => repo.repository_id === repositoryId)) : items)).catch(() => setError("Sign in to Audits to view recorded checks and repair plans."));
  }, [repositoryId]);
  return <section className="healthDashboard" aria-label="Recorded repository audits">
    <div className="healthDashboardHead"><div><p className="label">RECORDED AUDITS</p><h2>Repository checks and reviewed repairs</h2></div><Link href="/audits">Open Audits ↗</Link></div>
    {error ? <p>{error}</p> : runs.length === 0 ? <p>No audits recorded yet. Run repository checks from the Audits page.</p> :
      <div className="auditCardGrid">{runs.slice(0, 3).map(run => <article className="auditStatusCard" key={run.id}>
        <p className="label">{new Date(run.created_at).toLocaleString()}</p><h2>{run.summary.completed}/{run.summary.total} repositories completed</h2>
        <p>{run.summary.awaiting_approval} plans awaiting approval · {run.summary.pr_ready} pull requests ready</p>
        <Link href={`/audits/runs/${run.id}`}>View recorded results →</Link>
      </article>)}</div>}
  </section>;
}
