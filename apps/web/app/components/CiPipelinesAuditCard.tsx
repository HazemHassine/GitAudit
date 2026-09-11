"use client";

import { useEffect, useState } from "react";
import { type CiAuditSummary, request } from "../lib/api";

export type CiPipelinesAuditCardProps = {
  repositoryId?: string;
  audit?: CiAuditSummary;
  onRefresh?: () => void;
};

export function CiPipelinesAuditCard({
  repositoryId,
  audit: initialAudit,
  onRefresh,
}: CiPipelinesAuditCardProps) {
  const [localAudit, setLocalAudit] = useState<CiAuditSummary | null>(null);
  const [loading, setLoading] = useState(!initialAudit);
  const [checking, setChecking] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [activeTab, setActiveTab] = useState<"findings" | "logs">("findings");

  const [prevRepoId, setPrevRepoId] = useState(repositoryId);
  const [prevInitialAudit, setPrevInitialAudit] = useState(initialAudit);
  if (prevRepoId !== repositoryId || prevInitialAudit !== initialAudit) {
    setPrevRepoId(repositoryId);
    setPrevInitialAudit(initialAudit);
    setLocalAudit(null);
    setLoading(!initialAudit);
  }

  const audit = localAudit ?? initialAudit ?? null;

  useEffect(() => {
    if (initialAudit) {
      return;
    }
    let isSubscribed = true;
    async function loadAudit() {
      try {
        const endpoint = repositoryId
          ? `/api/v1/repositories/${repositoryId}/ci-audit`
          : `/api/v1/ci-audit/summary`;
        const data = await request<CiAuditSummary>(endpoint);
        if (isSubscribed && data) {
          setLocalAudit(data);
        }
      } catch {
        // Leave audit as null or error state
      } finally {
        if (isSubscribed) {
          setLoading(false);
        }
      }
    }
    void loadAudit();
    return () => {
      isSubscribed = false;
    };
  }, [repositoryId, initialAudit]);

  const handleLintCheck = async () => {
    setChecking(true);
    try {
      const endpoint = repositoryId
        ? `/api/v1/repositories/${repositoryId}/ci-audit/lint`
        : `/api/v1/ci-audit/summary`;
      const data = await request<CiAuditSummary>(endpoint, { method: "POST" });
      if (data) {
        setLocalAudit(data);
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    } finally {
      setChecking(false);
      onRefresh?.();
    }
  };

  if (loading) {
    return (
      <div className="panel ciAuditCard" style={{ marginBottom: "20px" }}>
        <p className="label">ISSUE #4 / AUDIT: CI PIPELINES</p>
        <p style={{ font: "500 11px DM Mono", color: "var(--muted)" }}>Loading CI pipeline audit...</p>
      </div>
    );
  }

  if (!audit) {
    return (
      <div className="panel ciAuditCard" style={{ marginBottom: "20px" }}>
        <p className="label">ISSUE #4 / AUDIT: CI PIPELINES</p>
        <p style={{ font: "500 11px DM Mono", color: "var(--orange)" }}>CI pipeline audit data unavailable.</p>
      </div>
    );
  }

  // Remote repository scope check
  if (audit.scope === "remote") {
    return (
      <div className="panel ciAuditCard" style={{ marginBottom: "20px" }}>
        <div className="curationHead" style={{ borderBottom: "1px solid var(--line)", paddingBottom: "16px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <p className="label" style={{ margin: 0 }}>ISSUE #4 / AUDIT: CI PIPELINES</p>
              <span className="status attention">REMOTE REPOSITORY SCOPE</span>
            </div>
            <h2 style={{ margin: "4px 0 0", fontSize: "20px", letterSpacing: "-.02em" }}>
              Workflow Health &amp; CI Pipeline Audit
            </h2>
          </div>
        </div>
        <div style={{ marginTop: "16px", padding: "16px", background: "var(--paper)", border: "1px solid var(--line)", fontSize: "12px", color: "var(--muted)", lineHeight: 1.6 }}>
          <p style={{ margin: 0 }}>
            {audit.message ||
              "Local workflow files and actionlint checks are restricted to the local workspace. Remote repository workflows require GitHub Actions API inspection."}
          </p>
        </div>
      </div>
    );
  }

  const jules = audit.jules_session;
  const isActionlintUnavailable = audit.last_run_status === "unavailable" || audit.actionlint_passed === null;
  const isActionlintError = audit.last_run_status === "error";

  return (
    <div className="panel ciAuditCard" style={{ marginBottom: "20px" }}>
      {/* Header Section */}
      <div className="curationHead" style={{ borderBottom: "1px solid var(--line)", paddingBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
            <p className="label" style={{ margin: 0 }}>ISSUE #4 / AUDIT: CI PIPELINES</p>
            {checking ? (
              <span className="status attention" style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <span className="dotPulse" /> CHECKING ACTIONLINT...
              </span>
            ) : isActionlintUnavailable ? (
              <span className="status attention">ACTIONLINT UNAVAILABLE</span>
            ) : isActionlintError ? (
              <span className="status degraded">EXECUTION ERROR</span>
            ) : audit.actionlint_passed ? (
              <span className="status healthy">VALIDATED (0 ERRORS)</span>
            ) : (
              <span className="status degraded">LINT FAILED</span>
            )}
          </div>
          <h2 style={{ margin: "4px 0 0", fontSize: "20px", letterSpacing: "-.02em" }}>
            Workflow Health &amp; Jules CI Intelligence
          </h2>
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            className="refreshButton"
            disabled={checking}
            onClick={handleLintCheck}
            title="Run local actionlint validation"
          >
            {checking ? "Checking…" : "Verify Actionlint"}
          </button>
          <button
            className="refreshButton"
            onClick={() => setShowLogs(!showLogs)}
          >
            {showLogs ? "Hide Details" : "Inspect Workflows"}
          </button>
        </div>
      </div>

      {/* Discovered Workflows List */}
      <div style={{ marginTop: "16px" }}>
        <div className="sectionTitle" style={{ fontSize: "11px", marginBottom: "10px" }}>
          <span>MONITORED WORKFLOWS ({audit.workflows.length})</span>
          <small>
            {isActionlintUnavailable
              ? "LINTER NOT FOUND"
              : isActionlintError
                ? "LINTER ERROR"
                : audit.actionlint_passed
                  ? "DETERMINISTIC ACTIONLINT PASS"
                  : "ACTIONLINT ISSUES DETECTED"}
          </small>
        </div>
        {audit.workflows.length === 0 ? (
          <div className="panelEmpty" style={{ padding: "16px" }}>
            <b>No local workflow files</b>
            <span>No GitHub Actions workflows found in .github/workflows/.</span>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "10px" }}>
            {audit.workflows.map((wf) => {
              const statusColor =
                wf.lint_status === "valid"
                  ? "var(--mint)"
                  : wf.lint_status === "unavailable"
                    ? "var(--orange)"
                    : "#ef6767";

              return (
                <div
                  key={wf.path}
                  style={{
                    border: "1px solid var(--line)",
                    background: "var(--paper)",
                    padding: "12px 14px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <b style={{ fontSize: "12px", display: "block", color: "var(--ink)" }}>{wf.name}</b>
                    <code style={{ fontSize: "9px", color: "var(--muted)" }}>{wf.path}</code>
                  </div>
                  <span
                    style={{
                      fontSize: "9px",
                      fontFamily: "DM Mono, monospace",
                      color: statusColor,
                      fontWeight: 600,
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <i
                      style={{
                        display: "inline-block",
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        background: statusColor,
                      }}
                    />
                    {wf.lint_status.toUpperCase()}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Actionlint Output Drawer (Collapsible) */}
      {showLogs && (
        <div
          style={{
            marginTop: "12px",
            background: "var(--ink)",
            color: "#dce5dd",
            padding: "12px 16px",
            fontFamily: "DM Mono, monospace",
            fontSize: "10px",
            lineHeight: 1.6,
            overflowX: "auto",
            borderLeft: `3px solid ${
              audit.actionlint_passed
                ? "var(--mint)"
                : isActionlintUnavailable
                  ? "var(--orange)"
                  : "#ef6767"
            }`,
          }}
        >
          <div style={{ color: "var(--muted)", marginBottom: "4px" }}>$ actionlint</div>
          <div>{audit.actionlint_output || "No output recorded."}</div>
        </div>
      )}

      {/* Jules CI Intelligence Agent Feed */}
      {jules && (
        <div
          style={{
            marginTop: "20px",
            border: "1px solid var(--line)",
            background: "var(--panel)",
            padding: "16px 18px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "14px" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span
                  style={{
                    background: "#715cd720",
                    color: "#715cd7",
                    border: "1px solid #715cd740",
                    fontSize: "9px",
                    fontFamily: "DM Mono, monospace",
                    fontWeight: 600,
                    padding: "3px 6px",
                  }}
                >
                  JULES AI CI AGENT
                </span>
                {jules.session_id && (
                  <span style={{ fontSize: "10px", fontFamily: "DM Mono, monospace", color: "var(--muted)" }}>
                    Session: #{jules.session_id}
                  </span>
                )}
              </div>
              <h3 style={{ margin: "6px 0 0", fontSize: "14px", fontWeight: 600 }}>
                {jules.plan_status || "Autonomous CI Pipeline Analysis"}
              </h3>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                className={`status ${
                  jules.status === "in_progress"
                    ? "attention"
                    : jules.status === "failed"
                      ? "degraded"
                      : "healthy"
                }`}
                style={{ fontSize: "9px" }}
              >
                {jules.status === "in_progress" ? "● IN PROGRESS" : jules.status.toUpperCase()}
              </span>
              {jules.url && (
                <a
                  href={jules.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    fontSize: "9px",
                    fontFamily: "DM Mono, monospace",
                    color: "var(--ink)",
                    textDecoration: "underline",
                  }}
                >
                  Jules Console ↗
                </a>
              )}
            </div>
          </div>

          {/* Sub-tabs for Jules Insights */}
          <div style={{ display: "flex", gap: "8px", borderBottom: "1px solid var(--line)", paddingBottom: "8px", marginBottom: "12px" }}>
            <button
              onClick={() => setActiveTab("findings")}
              style={{
                border: 0,
                background: "none",
                fontFamily: "DM Mono, monospace",
                fontSize: "10px",
                fontWeight: activeTab === "findings" ? 600 : 400,
                color: activeTab === "findings" ? "var(--ink)" : "var(--muted)",
                cursor: "pointer",
                borderBottom: activeTab === "findings" ? "2px solid var(--ink)" : "2px solid transparent",
                paddingBottom: "4px",
              }}
            >
              Audited Findings &amp; Opportunities
            </button>
            <button
              onClick={() => setActiveTab("logs")}
              style={{
                border: 0,
                background: "none",
                fontFamily: "DM Mono, monospace",
                fontSize: "10px",
                fontWeight: activeTab === "logs" ? 600 : 400,
                color: activeTab === "logs" ? "var(--ink)" : "var(--muted)",
                cursor: "pointer",
                borderBottom: activeTab === "logs" ? "2px solid var(--ink)" : "2px solid transparent",
                paddingBottom: "4px",
              }}
            >
              Agent Execution Steps ({jules.logs.length})
            </button>
          </div>

          {activeTab === "findings" && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px" }}>
              {/* Bottlenecks Card */}
              {jules.bottlenecks.length > 0 && (
                <div style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: "12px" }}>
                  <span style={{ fontSize: "9px", fontFamily: "DM Mono, monospace", color: "var(--orange)", fontWeight: 600, display: "block", marginBottom: "6px" }}>
                    ⚡ BOTTLENECKS IDENTIFIED
                  </span>
                  <ul style={{ margin: 0, paddingLeft: "16px", fontSize: "11px", color: "var(--ink)", lineHeight: 1.5 }}>
                    {jules.bottlenecks.map((item, idx) => (
                      <li key={idx} style={{ marginBottom: "4px" }}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Parallelization Card */}
              {jules.parallelization_suggestions.length > 0 && (
                <div style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: "12px" }}>
                  <span style={{ fontSize: "9px", fontFamily: "DM Mono, monospace", color: "#28704c", fontWeight: 600, display: "block", marginBottom: "6px" }}>
                    🚀 PARALLELIZATION PROPOSALS
                  </span>
                  <ul style={{ margin: 0, paddingLeft: "16px", fontSize: "11px", color: "var(--ink)", lineHeight: 1.5 }}>
                    {jules.parallelization_suggestions.map((item, idx) => (
                      <li key={idx} style={{ marginBottom: "4px" }}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Flakiness Card */}
              {jules.flakiness_notes.length > 0 && (
                <div style={{ background: "var(--paper)", border: "1px solid var(--line)", padding: "12px" }}>
                  <span style={{ fontSize: "9px", fontFamily: "DM Mono, monospace", color: "#8b542f", fontWeight: 600, display: "block", marginBottom: "6px" }}>
                    🔄 FLAKINESS SAFEGUARDS
                  </span>
                  <ul style={{ margin: 0, paddingLeft: "16px", fontSize: "11px", color: "var(--ink)", lineHeight: 1.5 }}>
                    {jules.flakiness_notes.map((item, idx) => (
                      <li key={idx} style={{ marginBottom: "4px" }}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {activeTab === "logs" && (
            <div
              style={{
                background: "var(--ink)",
                color: "#dce5dd",
                padding: "12px 14px",
                fontFamily: "DM Mono, monospace",
                fontSize: "10px",
                lineHeight: 1.7,
                borderRadius: "2px",
              }}
            >
              {jules.logs.map((log, idx) => (
                <div key={idx} style={{ display: "flex", gap: "8px" }}>
                  <span style={{ color: "var(--mint)" }}>&gt;</span>
                  <span>{log}</span>
                </div>
              ))}
            </div>
          )}

          {/* Action Callout */}
          {jules.pull_request_url && (
            <div
              style={{
                marginTop: "12px",
                padding: "10px 14px",
                background: "#82f3bd18",
                border: "1px solid var(--mint)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ fontSize: "11px" }}>
                <b>Autonomous Optimization PR Ready:</b> Jules has prepared workflow improvements.
              </div>
              <a
                href={jules.pull_request_url}
                target="_blank"
                rel="noreferrer"
                style={{
                  fontFamily: "DM Mono, monospace",
                  fontSize: "9px",
                  fontWeight: 600,
                  color: "var(--ink)",
                  background: "var(--mint)",
                  padding: "6px 10px",
                  textDecoration: "none",
                  textTransform: "uppercase",
                }}
              >
                Review Pull Request ↗
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default CiPipelinesAuditCard;
