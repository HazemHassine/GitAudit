"use client";

type AuditStatus = "configured" | "unavailable" | "planned";

type AuditStatusCardProps = {
  issue: number;
  title: string;
  status: AuditStatus;
  summary: string;
  checks: readonly string[];
  command?: string;
};

export function AuditStatusCard({ issue, title, status, summary, checks, command }: AuditStatusCardProps) {
  const label = status === "configured" ? "Configured" : status === "planned" ? "Planned" : "Telemetry unavailable";
  return (
    <article className="auditStatusCard">
      <div className="auditStatusHead">
        <p className="label">ISSUE #{issue}</p>
        <span className={`status ${status}`}>{label}</span>
      </div>
      <h2>{title}</h2>
      <p>{summary}</p>
      <ul>{checks.map((check) => <li key={check}>{check}</li>)}</ul>
      {command && <code className="auditCommand">{command}</code>}
    </article>
  );
}
