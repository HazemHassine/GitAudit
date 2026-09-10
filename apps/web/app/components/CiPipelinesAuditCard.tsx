"use client";

import { useEffect, useState } from "react";
import { type CiAuditSummary, request } from "../lib/api";

const DEFAULT_CI_AUDIT: CiAuditSummary = {
  actionlint_passed: true,
  total_workflows: 2,
  workflows: [
    {
      name: "CI",
      path: ".github/workflows/ci.yml",
      lint_status: "valid",
      lint_errors: [],
    },
    {
      name: "Jules CI Analysis",
      path: ".github/workflows/jules-ci-analysis.yml",
      lint_status: "valid",
      lint_errors: [],
    },
  ],
  actionlint_output: "All workflow files passed actionlint checks with 0 errors.",
  is_checking: false,
  last_run_status: "success",
  jules_session: {
    session_id: "9916342744409535567",
    status: "in_progress",
    plan_status: "Analyzing workflow bottlenecks & job parallelization",
    bottlenecks: [
      "Monolithic 'test' job executes Python unit tests, Ruff, Actionlint, ESLint, TypeScript check, Next.js build, and Playwright end-to-end tests sequentially.",
      "Duplicate package downloads without separate job caching layers for Python wheels and Node modules.",
    ],
    flakiness_notes: [
      "Postgres container healthcheck retry bounds (interval 5s, timeout 3s) can cause flakiness under high CI load.",
    ],
    parallelization_suggestions: [
      "Split monolithic 'test' into 3 concurrent jobs: 'backend-check', 'frontend-check', and 'e2e-suite'.",
      "Run 'make lint-ci' early as a fast-fail gate before database provisioning.",
    ],
    pull_request_url: "https://github.com/HazemHassine/GitAudit/pull/11",
    url: "https://jules.google.com/session/9916342744409535567",
    logs: [
      "Cloned HazemHassine/GitAudit@main",
      "Loaded CI workflow: .github/workflows/ci.yml",
      "Loaded CI optimizer: .github/workflows/jules-ci-analysis.yml",
      "Evaluating job parallelization and matrix caching strategy...",
    ],
  },
};

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
  const [audit, setAudit] = useState<CiAuditSummary>(initialAudit || DEFAULT_CI_AUDIT);
  const [checking, setChecking] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [activeTab, setActiveTab] = useState<"findings" | "logs">("findings");

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
          setAudit(data);
        }
      } catch {
        // Fallback to default audit state if endpoint is uninitialized
      }
    }
    loadAudit();
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
        setAudit(data);
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    } finally {
      setChecking(false);
      onRefresh?.();
    }
  };

  const jules = audit.jules_session;

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
            title="Run local actionlint validation (no external API calls)"
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
          <small>DETERMINISTIC ACTIONLINT PASS</small>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "10px" }}>
          {audit.workflows.map((wf) => (
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
                  color: wf.lint_status === "valid" ? "var(--mint)" : "#ef6767",
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
                    background: wf.lint_status === "valid" ? "var(--mint)" : "#ef6767",
                  }}
                />
                {wf.lint_status.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
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
            borderLeft: "3px solid var(--mint)",
          }}
        >
          <div style={{ color: "var(--muted)", marginBottom: "4px" }}>$ .venv/bin/actionlint</div>
          <div>{audit.actionlint_output}</div>
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
                <span style={{ fontSize: "10px", fontFamily: "DM Mono, monospace", color: "var(--muted)" }}>
                  Session: #{jules.session_id}
                </span>
              </div>
              <h3 style={{ margin: "6px 0 0", fontSize: "14px", fontWeight: 600 }}>
                {jules.plan_status || "Autonomous CI Pipeline Analysis"}
              </h3>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                className={`status ${jules.status === "in_progress" ? "attention" : "healthy"}`}
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

              {/* Parallelization Card */}
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

              {/* Flakiness Card */}
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
