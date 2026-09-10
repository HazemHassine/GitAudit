"use client";

import { useEffect, useState } from "react";
import { API_URL, CoverageSummary, JulesCoverageSession, request } from "../lib/api";

type CoverageCardProps = {
  repositoryId?: string;
};

export default function CoverageCard({ repositoryId }: CoverageCardProps) {
  const [summary, setSummary] = useState<CoverageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [julesSession, setJulesSession] = useState<JulesCoverageSession | null>(null);
  const [streamLogs, setStreamLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [prevRepoId, setPrevRepoId] = useState(repositoryId);
  if (prevRepoId !== repositoryId) {
    setPrevRepoId(repositoryId);
    setSummary(null);
    setLoading(true);
    setGenerating(false);
    setJulesSession(null);
    setStreamLogs([]);
    setError(null);
  }

  useEffect(() => {
    let isSubscribed = true;

    async function loadCoverage() {
      try {
        const endpoint = repositoryId
          ? `/api/v1/repositories/${repositoryId}/coverage`
          : `/api/v1/coverage/summary`;
        const data = await request<CoverageSummary>(endpoint);
        if (isSubscribed) {
          setSummary(data);
          if (data.jules_session) {
            setJulesSession(data.jules_session);
          }
          setLoading(false);
        }
      } catch (e) {
        if (isSubscribed) {
          setError(e instanceof Error ? e.message : "Failed to load coverage");
          setLoading(false);
        }
      }
    }

    void loadCoverage();

    // Listen to SSE coverage stream only when in global (unscoped) mode
    let eventSource: EventSource | null = null;
    if (!repositoryId) {
      try {
        eventSource = new EventSource(`${API_URL}/api/v1/coverage/stream`);
        eventSource.addEventListener("coverage_snapshot", (e) => {
          if (!isSubscribed) return;
          try {
            const parsed = JSON.parse(e.data);
            setSummary(parsed);
            if (parsed.jules_session) setJulesSession(parsed.jules_session);
          } catch {}
        });
        eventSource.addEventListener("session_update", (e) => {
          if (!isSubscribed) return;
          try {
            const parsed = JSON.parse(e.data);
            setJulesSession(parsed);
            if (parsed.logs) {
              setStreamLogs((prev) => [...prev, ...parsed.logs.slice(-3)]);
            }
          } catch {}
        });
      } catch {}
    }

    return () => {
      isSubscribed = false;
      if (eventSource) eventSource.close();
    };
  }, [repositoryId]);

  const handleGenerateTests = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await request<JulesCoverageSession>("/api/v1/coverage/generate-tests", {
        method: "POST",
        body: JSON.stringify({
          focus_module: "curation.py, github.py, reproduction.py",
          target_coverage: 80.0,
          dry_run: false,
        }),
      });
      setJulesSession(res);
      if (res.logs) {
        setStreamLogs((prev) => [...prev, ...(res.logs ?? [])]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to invoke Jules test generator");
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="curationPanel" style={{ marginBottom: "20px" }}>
        <p className="label">MILESTONE 4 / TEST COVERAGE & QUALITY (ISSUE #3)</p>
        <p style={{ font: "500 11px DM Mono", color: "var(--muted)" }}>Loading coverage telemetry...</p>
      </div>
    );
  }

  // Check remote repository scope
  if (summary?.scope === "remote") {
    return (
      <section className="curationPanel" style={{ marginBottom: "24px" }}>
        <div className="curationHead">
          <div>
            <p className="label">MILESTONE 4 / TEST COVERAGE & QUALITY (ISSUE #3)</p>
            <h2>Test Execution & Coverage Sentinel</h2>
          </div>
          <div className="curationVerdict">
            <span style={{ color: "var(--orange)" }}>REMOTE REPOSITORY SCOPE</span>
            <b>Telemetry Unavailable</b>
          </div>
        </div>
        <div
          style={{
            marginTop: "16px",
            padding: "16px",
            background: "var(--panel)",
            border: "1px solid var(--line)",
            fontSize: "12px",
            color: "var(--muted)",
            lineHeight: 1.6,
          }}
        >
          <p style={{ margin: 0 }}>
            {summary.message ||
              "Local coverage telemetry is not available for remote repositories. Evidence collection requires local workspace test execution or integrating CI coverage artifacts."}
          </p>
        </div>
      </section>
    );
  }

  const isAvailable = summary?.status === "available" && summary.coverage_percent !== null;
  const isError = summary?.status === "error";
  const covPct = summary?.coverage_percent ?? null;
  const threshold = summary?.threshold_percent ?? 80.0;
  const passed = covPct !== null ? covPct >= threshold : false;

  return (
    <section className="curationPanel" style={{ marginBottom: "24px" }}>
      <div className="curationHead">
        <div>
          <p className="label">MILESTONE 4 / TEST COVERAGE & QUALITY (ISSUE #3)</p>
          <h2>Test Execution & Coverage Sentinel</h2>
        </div>
        <div className="curationVerdict">
          {isAvailable ? (
            <>
              <span style={{ color: passed ? "var(--mint)" : "var(--orange)" }}>
                {passed ? "80% GATE PASSED" : "GATE VIOLATION"}
              </span>
              <b>{covPct}% Coverage</b>
            </>
          ) : isError ? (
            <>
              <span style={{ color: "#ef6767" }}>PARSING ERROR</span>
              <b>Invalid XML</b>
            </>
          ) : (
            <>
              <span style={{ color: "var(--orange)" }}>NO EVIDENCE</span>
              <b>Coverage Unavailable</b>
            </>
          )}
        </div>
      </div>

      {error && <div className="inlineError" style={{ margin: "12px 0" }}>{error}</div>}
      {summary?.message && !isAvailable && (
        <div
          style={{
            margin: "12px 0",
            padding: "10px 14px",
            background: isError ? "rgba(239, 103, 103, 0.1)" : "rgba(255, 153, 106, 0.1)",
            border: `1px solid ${isError ? "#ef6767" : "var(--orange)"}`,
            fontSize: "11px",
            fontFamily: "DM Mono, monospace",
          }}
        >
          {summary.message}
        </div>
      )}

      {/* Primary Metrics Row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "12px",
          marginTop: "16px",
          padding: "16px",
          background: "var(--panel)",
          border: "1px solid var(--line)",
        }}
      >
        <div>
          <span style={{ font: "500 9px DM Mono", color: "var(--muted)", textTransform: "uppercase" }}>
            Current Coverage
          </span>
          <div style={{ font: "400 28px DM Mono", color: isAvailable ? (passed ? "#28704c" : "#b0481a") : "var(--muted)", marginTop: "4px" }}>
            {covPct !== null ? `${covPct}%` : "—"}
          </div>
          <small style={{ font: "10px DM Mono", color: "var(--muted)" }}>
            Target threshold: {threshold}%
          </small>
        </div>

        <div>
          <span style={{ font: "500 9px DM Mono", color: "var(--muted)", textTransform: "uppercase" }}>
            Statements Covered
          </span>
          <div style={{ font: "400 28px DM Mono", marginTop: "4px" }}>
            {isAvailable ? (
              <>
                {summary.total_statements - summary.total_missed}
                <small style={{ fontSize: "14px", color: "var(--muted)" }}>
                  /{summary.total_statements}
                </small>
              </>
            ) : (
              "—"
            )}
          </div>
          <small style={{ font: "10px DM Mono", color: "var(--muted)" }}>
            {isAvailable ? `${summary.total_missed} missed branches` : "No statement telemetry"}
          </small>
        </div>

        <div>
          <span style={{ font: "500 9px DM Mono", color: "var(--muted)", textTransform: "uppercase" }}>
            Pytest Suite Status
          </span>
          <div style={{ font: "400 28px DM Mono", color: summary?.tests_passed != null ? "#28704c" : "var(--muted)", marginTop: "4px" }}>
            {summary?.tests_passed != null ? `${summary.tests_passed} PASS` : "—"}
          </div>
          <small style={{ font: "10px DM Mono", color: "var(--muted)" }}>
            {summary?.tests_passed != null && summary?.total_tests != null
              ? `${summary.total_tests - summary.tests_passed} failures · ${summary.execution_time_seconds ?? 0}s runtime`
              : "Test counts not in coverage report"}
          </small>
        </div>

        <div>
          <span style={{ font: "500 9px DM Mono", color: "var(--muted)", textTransform: "uppercase" }}>
            CI Pipeline Gate
          </span>
          <div style={{ marginTop: "6px" }}>
            <span
              style={{
                display: "inline-block",
                padding: "4px 8px",
                font: "500 10px DM Mono",
                background: isAvailable
                  ? passed
                    ? "rgba(130, 243, 189, 0.25)"
                    : "rgba(255, 153, 106, 0.25)"
                  : "rgba(23, 33, 29, 0.08)",
                color: isAvailable
                  ? passed
                    ? "#28704c"
                    : "#b0481a"
                  : "var(--muted)",
                border: `1px solid ${
                  isAvailable
                    ? passed
                      ? "var(--mint)"
                      : "var(--orange)"
                    : "var(--line)"
                }`,
              }}
            >
              {isAvailable
                ? passed
                  ? "✓ ENFORCED & PASSING"
                  : "⚠ BLOCKS MERGE"
                : "NO EVIDENCE RECORDED"}
            </span>
          </div>
          <small style={{ font: "10px DM Mono", color: "var(--muted)", display: "block", marginTop: "4px" }}>
            pytest-cov in CI &amp; Makefile
          </small>
        </div>
      </div>

      {/* Visual Meter Bar */}
      <div style={{ marginTop: "16px", padding: "12px 16px", background: "var(--panel)", border: "1px solid var(--line)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", font: "500 9px DM Mono", marginBottom: "6px" }}>
          <span>COVERAGE PROGRESSION</span>
          <span>{covPct !== null ? `${covPct}%` : "0%"} / 100% (GATE: {threshold}%)</span>
        </div>
        <div style={{ position: "relative", height: "10px", background: "#e8e6df", borderRadius: "2px", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: `${Math.min(100, Math.max(0, covPct ?? 0))}%`,
              background: isAvailable ? (passed ? "var(--mint)" : "var(--orange)") : "transparent",
              transition: "width 0.4s ease",
            }}
          />
          {/* Threshold marker at 80% */}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${threshold}%`,
              width: "2px",
              background: "var(--ink)",
              zIndex: 2,
            }}
            title={`Minimum Threshold: ${threshold}%`}
          />
        </div>
      </div>

      {/* Module Breakdown */}
      {summary?.modules && summary.modules.length > 0 && (
        <div style={{ marginTop: "16px" }}>
          <div className="sectionTitle">
            <span>MODULE COVERAGE BREAKDOWN</span>
            <small>{summary.modules.length} MODULES AUDITED</small>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "8px", marginTop: "10px" }}>
            {summary.modules.map((mod) => (
              <div
                key={mod.name}
                style={{
                  padding: "10px 12px",
                  background: "var(--panel)",
                  border: "1px solid var(--line)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "4px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", font: "500 11px DM Mono" }}>
                  <code style={{ fontWeight: 600 }}>{mod.name}</code>
                  <span style={{ color: mod.coverage_percent >= 80 ? "#28704c" : "#b0481a" }}>
                    {mod.coverage_percent}%
                  </span>
                </div>
                <div style={{ height: "4px", background: "#e8e6df", borderRadius: "1px", overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${Math.min(100, mod.coverage_percent)}%`,
                      background: mod.coverage_percent >= 80 ? "var(--mint)" : "var(--orange)",
                    }}
                  />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", font: "9px DM Mono", color: "var(--muted)" }}>
                  <span>{mod.statements - mod.missed}/{mod.statements} lines</span>
                  <span>{mod.missed > 0 ? `${mod.missed} missed` : "100% covered"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Jules Automated Test Generator Section */}
      <div
        style={{
          marginTop: "20px",
          padding: "18px",
          background: "#f7f6f0",
          border: "1px solid var(--ink)",
          boxShadow: "4px 4px 0 #17211d15",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <div style={{ font: "500 10px DM Mono", color: "var(--ink)", letterSpacing: ".08em" }}>
              🤖 GOOGLE LABS JULES API / AUTO_CREATE_PR
            </div>
            <h3 style={{ margin: "4px 0", fontSize: "16px" }}>Autonomous Edge-Case Test Synthesis</h3>
            <p style={{ margin: 0, fontSize: "12px", color: "var(--muted)", maxWidth: "560px" }}>
              Jules analyzes untested branches in isolated cloud containers and opens pull requests with synthesized pytest unit/integration assertions.
            </p>
          </div>

          <button
            onClick={handleGenerateTests}
            disabled={generating}
            style={{
              padding: "9px 16px",
              background: "var(--ink)",
              color: "white",
              border: 0,
              font: "500 10px DM Mono",
              textTransform: "uppercase",
              cursor: generating ? "wait" : "pointer",
              letterSpacing: ".05em",
            }}
          >
            {generating ? "Synthesizing Tests..." : "Generate Tests via Jules (AUTO_CREATE_PR)"}
          </button>
        </div>

        {julesSession && (
          <div style={{ marginTop: "14px", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", font: "500 10px DM Mono", marginBottom: "8px" }}>
              <span>
                SESSION: <code>{julesSession.session_id}</code>
              </span>
              <span
                style={{
                  padding: "3px 6px",
                  background:
                    julesSession.status === "completed"
                      ? "var(--mint)"
                      : julesSession.status === "preview"
                        ? "rgba(113, 92, 215, 0.2)"
                        : julesSession.status === "failed"
                          ? "rgba(239, 103, 103, 0.2)"
                          : "rgba(23,33,29,0.08)",
                  color:
                    julesSession.status === "failed"
                      ? "#b0481a"
                      : julesSession.status === "preview"
                        ? "#715cd7"
                        : "var(--ink)",
                  textTransform: "uppercase",
                }}
              >
                STATUS: {julesSession.status}
              </span>
            </div>

            {julesSession.plan_status && (
              <p style={{ fontSize: "12px", fontStyle: "italic", margin: "4px 0 8px", color: "var(--ink)" }}>
                Active Plan: {julesSession.plan_status}
              </p>
            )}

            {julesSession.untested_cases && julesSession.untested_cases.length > 0 && (
              <div style={{ marginTop: "8px" }}>
                <span style={{ font: "500 9px DM Mono", color: "var(--muted)", textTransform: "uppercase" }}>
                  Targeted Untested Edge Cases:
                </span>
                <ul style={{ margin: "4px 0 10px", paddingLeft: "18px", fontSize: "11px", color: "var(--ink)" }}>
                  {julesSession.untested_cases.map((uc, i) => (
                    <li key={i} style={{ marginBottom: "2px" }}><code>{uc}</code></li>
                  ))}
                </ul>
              </div>
            )}

            {julesSession.pull_request_url && (
              <div style={{ marginTop: "8px" }}>
                <a
                  href={julesSession.pull_request_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "6px 12px",
                    background: "var(--mint)",
                    color: "var(--ink)",
                    textDecoration: "none",
                    font: "600 10px DM Mono",
                    textTransform: "uppercase",
                  }}
                >
                  🚀 Pull Request Created: View Generated PR ↗
                </a>
              </div>
            )}

            {streamLogs.length > 0 && (
              <div
                style={{
                  marginTop: "10px",
                  padding: "8px 10px",
                  background: "var(--ink)",
                  color: "#d8d7cf",
                  font: "10px DM Mono",
                  maxHeight: "90px",
                  overflowY: "auto",
                }}
              >
                {streamLogs.map((log, i) => (
                  <div key={i}>&gt; {log}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
