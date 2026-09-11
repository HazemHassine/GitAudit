"use client";

import { useEffect, useState } from "react";

import { type CoverageSummary, request } from "../lib/api";

type CoverageCardProps = {
  repositoryId?: string;
};

export default function CoverageCard({ repositoryId }: CoverageCardProps) {
  const [summary, setSummary] = useState<CoverageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const endpoint = repositoryId
      ? `/api/v1/repositories/${repositoryId}/coverage`
      : "/api/v1/coverage/summary";

    async function loadCoverage() {
      try {
        const data = await request<CoverageSummary>(endpoint);
        if (active) {
          setSummary(data);
          setError(null);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load coverage");
      }
    }

    void loadCoverage();
    return () => { active = false; };
  }, [repositoryId]);

  const coverage = summary?.coverage_percent ?? null;
  const threshold = summary?.threshold_percent ?? 80;
  const available = summary?.status === "available" && coverage !== null;
  const passes = available && coverage >= threshold;

  return (
    <article className="auditStatusCard coverageAuditCard">
      <div className="auditStatusHead">
        <p className="label">ISSUE #3</p>
        <span className={`status ${available ? (passes ? "configured" : "planned") : "planned"}`}>
          {available ? (passes ? "Gate passing" : "Below gate") : "Evidence unavailable"}
        </span>
      </div>
      <h2>Test coverage &amp; quality</h2>
      {error ? (
        <p className="inlineError">{error}</p>
      ) : summary?.scope === "remote" ? (
        <p>{summary.message}</p>
      ) : (
        <>
          <div className="coverageMetric">
            <b>{coverage === null ? "—" : `${coverage}%`}</b>
            <span>target {threshold}%</span>
          </div>
          <div className="coverageMeter" aria-label={`Coverage ${coverage ?? "unavailable"} percent`}>
            <i style={{ width: `${Math.max(0, Math.min(coverage ?? 0, 100))}%` }} />
            <em style={{ left: `${threshold}%` }} />
          </div>
          <p>
            {available
              ? `${summary.total_statements - summary.total_missed}/${summary.total_statements} statements covered.`
              : summary?.message ?? "Run the coverage target to collect local evidence."}
          </p>
          {summary?.modules.length ? (
            <details className="coverageModules">
              <summary>{summary.modules.length} measured modules</summary>
              <ul>
                {summary.modules.slice(0, 8).map((module) => (
                  <li key={module.name}>
                    <code>{module.name}</code><span>{module.coverage_percent}%</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
      <code className="auditCommand">make test-cov</code>
    </article>
  );
}
