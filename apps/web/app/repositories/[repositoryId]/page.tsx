"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Navigation } from "../../components/Navigation";
import {
  type CurationAssessment,
  type Repository,
  type Scan,
  type ReproductionRun,
  label,
  relativeTime,
  repositoryDisplayStatus,
  request,
} from "../../lib/api";


function formatDate(value: string | null): string {
  if (!value) return "Not completed";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}


export default function RepositoryReport() {
  const { repositoryId } = useParams<{ repositoryId: string }>();
  const router = useRouter();
  const [repository, setRepository] = useState<Repository | null>(null);
  const [history, setHistory] = useState<Scan[]>([]);
  const [assessments, setAssessments] = useState<CurationAssessment[]>([]);
  const [reproductions, setReproductions] = useState<ReproductionRun[]>([]);
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextRepository, nextHistory, nextAssessments, nextReproductions] = await Promise.all([
        request<Repository>(`/api/v1/repositories/${repositoryId}`),
        request<Scan[]>(`/api/v1/repositories/${repositoryId}/scans`),
        request<CurationAssessment[]>(`/api/v1/repositories/${repositoryId}/assessments`),
        request<ReproductionRun[]>(`/api/v1/repositories/${repositoryId}/reproductions`).catch(() => []),
      ]);
      setRepository(nextRepository);
      setHistory(nextHistory);
      setAssessments(nextAssessments);
      setReproductions(nextReproductions);
      setSelectedScanId((current) =>
        current && nextHistory.some((scan) => scan.id === current)
          ? current
          : (nextHistory[0]?.id ?? null),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load repository report");
    }
  }, [repositoryId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const selectedScan =
    history.find((scan) => scan.id === selectedScanId) ?? history[0] ?? null;
  const latestCompleted = history.find((scan) => scan.report);
  const previousCompleted = history.filter((scan) => scan.report)[1];
  const comparison = useMemo(() => {
    if (!latestCompleted?.report) return [];
    const previous = new Map(
      previousCompleted?.report?.dimensions.map((dimension) => [
        dimension.dimension,
        dimension.score,
      ]) ?? [],
    );
    return latestCompleted.report.dimensions.map((dimension) => ({
      ...dimension,
      previous: previous.get(dimension.dimension),
      delta:
        previous.has(dimension.dimension)
          ? dimension.score - (previous.get(dimension.dimension) ?? 0)
          : null,
    }));
  }, [latestCompleted, previousCompleted]);

  async function scanNow() {
    setBusy(true);
    setError(null);
    try {
      await request(`/api/v1/repositories/${repositoryId}/scans`, { method: "POST" });
      await load();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Repository scan failed";
      await load();
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function assessProfile() {
    setBusy(true);
    setError(null);
    try {
      await request<CurationAssessment>(`/api/v1/repositories/${repositoryId}/assessments`, {
        method: "POST",
      });
      await load();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Profile assessment failed";
      await load();
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function stopMonitoring() {
    if (!repository) return;
    const confirmed = window.confirm(
      `Stop automatically monitoring ${repository.owner}/${repository.name}? Its scan history will be retained.`,
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await request(`/api/v1/repositories/${repositoryId}`, { method: "DELETE" });
      router.push("/");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to stop monitoring");
      setBusy(false);
    }
  }

  async function reproduceFailure() {
    setBusy(true);
    setError(null);
    try {
      const run = await request<ReproductionRun>(`/api/v1/reproductions`, {
        method: "POST",
        body: JSON.stringify({
          commit_sha: repository?.default_branch_sha || undefined,
        }),
      });
      router.push(`/repositories/${repositoryId}/reproductions/${run.id}`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Reproduction failed";
      await load();
      setError(message);
      setBusy(false);
    }
  }

  const status = repository ? repositoryDisplayStatus(repository) : "unscanned";
  const latestAssessment = assessments[0] ?? null;

  return (
    <main className="shell">
      <Navigation active="repositories" />
      <section className="workspace reportWorkspace">
        <header>
          <div>
            <p className="eyebrow">
              <Link href="/">COMMAND CENTER</Link> / REPOSITORY REPORT
            </p>
            <h1>{repository ? `${repository.owner}/${repository.name}` : "Loading report…"}</h1>
          </div>
          <div className="reportActions">
            {repository?.html_url && (
              <a href={repository.html_url} target="_blank" rel="noreferrer">
                GitHub ↗
              </a>
            )}
            <button disabled={busy} onClick={() => void scanNow()}>
              {busy ? "Scanning…" : "Scan now"}
            </button>
            <button disabled={busy} onClick={() => void assessProfile()}>
              {busy ? "Working…" : "Assess profile"}
            </button>
            <button disabled={busy} onClick={() => void reproduceFailure()}>
              {busy ? "Working…" : "Investigate & Reproduce"}
            </button>
            <button className="quietButton" disabled={busy} onClick={() => void stopMonitoring()}>
              Stop monitoring
            </button>
          </div>
        </header>

        {error && (
          <div className="errorBanner" role="alert">
            <b>REPORT ERROR</b>
            <span>{error}</span>
            <button onClick={() => void load()}>Retry</button>
          </div>
        )}

        {repository && (
          <section className="reportIdentity">
            <div>
              <span>STATUS</span>
              <b className={`status ${status}`}>{label(status)}</b>
            </div>
            <div>
              <span>LATEST SCORE</span>
              <b>{repository.health?.overall_score ?? "—"}/100</b>
            </div>
            <div>
              <span>EVIDENCE COVERAGE</span>
              <b>{repository.health?.coverage_percent ?? 0}%</b>
            </div>
            <div>
              <span>DEFAULT SHA</span>
              <b>{repository.default_branch_sha?.slice(0, 12) ?? "Unknown"}</b>
            </div>
            <div>
              <span>OBSERVED</span>
              <b>
                {relativeTime(repository.last_scanned_at)}
                {repository.evidence_stale ? " · STALE" : ""}
              </b>
            </div>
          </section>
        )}

        <section className="curationPanel">
          <div className="curationHead">
            <div>
              <p className="label">MILESTONE 2 / AI PROFILE CURATOR</p>
              <h2>Repository positioning and maintenance proposals</h2>
            </div>
            {latestAssessment?.analysis && (
              <div className="curationVerdict">
                <span>{label(latestAssessment.analysis.classification)}</span>
                <b>{latestAssessment.analysis.confidence}% confidence</b>
              </div>
            )}
          </div>

          {!latestAssessment && (
            <div className="curationEmpty">
              <b>No AI assessment yet</b>
              <span>
                Review relevance, description, topics, README, and CI evidence. The curator only
                proposes changes; it cannot modify GitHub.
              </span>
              <button disabled={busy} onClick={() => void assessProfile()}>
                Assess this repository
              </button>
            </div>
          )}

          {latestAssessment?.status === "running" && (
            <div className="curationEmpty" aria-live="polite">
              <b>Assessment in progress</b>
              <span>The LangGraph workflow is collecting evidence and preparing proposals.</span>
            </div>
          )}

          {latestAssessment?.error && (
            <div className="inlineError">{latestAssessment.error}</div>
          )}

          {latestAssessment?.analysis && (
            <>
              <p className="curationSummary">{latestAssessment.analysis.summary}</p>
              <div className="curationSignals">
                <div>
                  <span>STRENGTHS</span>
                  {latestAssessment.analysis.strengths.map((strength) => (
                    <p key={strength}>{strength}</p>
                  ))}
                  {!latestAssessment.analysis.strengths.length && <p>No strengths asserted.</p>}
                </div>
                <div>
                  <span>CONCERNS</span>
                  {latestAssessment.analysis.concerns.map((concern) => (
                    <p key={concern}>{concern}</p>
                  ))}
                  {!latestAssessment.analysis.concerns.length && <p>No material concerns found.</p>}
                </div>
              </div>
              <div className="recommendationList">
                <div className="sectionTitle">
                  <span>PROPOSALS ONLY</span>
                  <small>
                    {latestAssessment.analysis.recommendations.length} RECOMMENDATIONS
                  </small>
                </div>
                {latestAssessment.analysis.recommendations.map((recommendation, index) => (
                  <article key={`${recommendation.kind}:${index}`}>
                    <div className="recommendationMeta">
                      <span>{label(recommendation.kind)}</span>
                      <b className={recommendation.priority}>{label(recommendation.priority)}</b>
                    </div>
                    <h3>{recommendation.title}</h3>
                    <p>{recommendation.rationale}</p>
                    {recommendation.suggested_description && (
                      <blockquote>{recommendation.suggested_description}</blockquote>
                    )}
                    {!!recommendation.suggested_topics.length && (
                      <div className="topicList">
                        {recommendation.suggested_topics.map((topic) => (
                          <code key={topic}>{topic}</code>
                        ))}
                      </div>
                    )}
                    {!!recommendation.readme_plan.length && (
                      <ul>
                        {recommendation.readme_plan.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    )}
                    {!!recommendation.evidence.length && (
                      <small>Evidence: {recommendation.evidence.join(" · ")}</small>
                    )}
                  </article>
                ))}
                {!latestAssessment.analysis.recommendations.length && (
                  <div className="panelEmpty">
                    <b>No changes proposed</b>
                    <span>The profile evidence looks adequate.</span>
                  </div>
                )}
              </div>
              <footer className="curationProvenance">
                <span>
                  {latestAssessment.model} · {latestAssessment.prompt_version}
                </span>
                <span>{formatDate(latestAssessment.completed_at)}</span>
              </footer>
            </>
          )}
        </section>

        <section className="curationPanel" style={{ marginBottom: "20px" }}>
          <div className="curationHead">
            <div>
              <p className="label">MILESTONE 3 / REPRODUCTION ENGINE</p>
              <h2>Past Reproductions</h2>
            </div>
          </div>
          
          <div className="historyList" style={{ marginTop: "16px" }}>
            {reproductions.map((run) => (
              <button
                key={run.id}
                onClick={() => router.push(`/repositories/${repositoryId}/reproductions/${run.id}`)}
              >
                <i className={run.status} />
                <span>
                  <b>{formatDate(run.started_at)}</b>
                  <small>{run.commit_sha.slice(0, 7)}</small>
                </span>
                <strong>{run.detected_stack || "Unknown"}</strong>
                <em>{run.current_phase === "completed" && run.exit_code === 0 ? "SUCCESS" : run.current_phase === "failed" || run.exit_code !== 0 ? "FAILED" : run.current_phase.toUpperCase()}</em>
              </button>
            ))}
            {!reproductions.length && (
              <div className="panelEmpty">
                <b>No historic reproductions</b>
                <span>Click Investigate & Reproduce to run a sandbox.</span>
              </div>
            )}
          </div>
        </section>

        <section className="reportGrid">
          <div className="panel comparisonPanel">
            <div className="sectionTitle">
              <span>LATEST VS PREVIOUS</span>
              <small>{previousCompleted ? "DIMENSION DELTA" : "FIRST SNAPSHOT"}</small>
            </div>
            {comparison.map((dimension) => (
              <div className="comparisonRow" key={dimension.dimension}>
                <span>{label(dimension.dimension)}</span>
                <b>{dimension.contributions.length ? dimension.score : label(dimension.status)}</b>
                <em
                  className={
                    dimension.delta === null
                      ? "neutral"
                      : dimension.delta > 0
                        ? "positive"
                        : dimension.delta < 0
                          ? "negative"
                          : "neutral"
                  }
                >
                  {dimension.delta === null
                    ? "NEW"
                    : dimension.delta > 0
                      ? `+${dimension.delta}`
                      : dimension.delta}
                </em>
              </div>
            ))}
            {!comparison.length && (
              <div className="panelEmpty">
                <b>No comparable reports</b>
                <span>A successful scan will create the first snapshot.</span>
              </div>
            )}
          </div>

          <div className="panel historyPanel">
            <div className="sectionTitle">
              <span>SCAN HISTORY</span>
              <small>{history.length} SNAPSHOTS</small>
            </div>
            <div className="historyList">
              {history.map((scan) => (
                <button
                  className={scan.id === selectedScan?.id ? "selected" : ""}
                  key={scan.id}
                  onClick={() => setSelectedScanId(scan.id)}
                >
                  <i className={scan.status} />
                  <span>
                    <b>{formatDate(scan.completed_at ?? scan.started_at)}</b>
                    <small>{scan.base_sha?.slice(0, 10) ?? "No commit captured"}</small>
                  </span>
                  <strong>{scan.report?.overall_score ?? "—"}</strong>
                  <em>{label(scan.status)}</em>
                </button>
              ))}
              {!history.length && (
                <div className="panelEmpty">
                  <b>No scan attempts</b>
                  <span>Run a scan to establish history.</span>
                </div>
              )}
            </div>
          </div>
        </section>

        {selectedScan && (
          <section className="scanReport">
            <div className="scanReportHead">
              <div>
                <p className="label">SCAN / {selectedScan.id}</p>
                <h2>Evidence at {selectedScan.base_sha?.slice(0, 12) ?? "unknown commit"}</h2>
              </div>
              <span className={`status ${selectedScan.status}`}>{label(selectedScan.status)}</span>
            </div>

            {selectedScan.error && <div className="inlineError">{selectedScan.error}</div>}
            {!!selectedScan.source_failures.length && (
              <div className="sourceFailures">
                <b>PARTIAL COLLECTION</b>
                {selectedScan.source_failures.map((failure) => (
                  <span key={failure}>{failure}</span>
                ))}
              </div>
            )}

            <div className="evidenceGrid">
              {selectedScan.signals.map((signal) => (
                <article key={signal.key}>
                  <div className="evidenceHead">
                    <span>{label(signal.dimension)}</span>
                    <b className={signal.status}>{label(signal.status)}</b>
                  </div>
                  <h3>{signal.summary}</h3>
                  <p>{signal.evidence.summary}</p>
                  <small>Observed {formatDate(signal.evidence.observed_at)}</small>
                  {signal.dimension === "ci" && signal.status === "fail" && (
                    <button
                      className="quietButton"
                      style={{ marginTop: "10px", width: "100%", padding: "6px", cursor: "pointer", background: "var(--ink)", color: "white", border: "0", font: "500 8px DM Mono", textTransform: "uppercase" }}
                      onClick={() => void reproduceFailure()}
                      disabled={busy}
                    >
                      Reproduce CI Failure
                    </button>
                  )}
                  {signal.evidence.url && (
                    <a href={signal.evidence.url} target="_blank" rel="noreferrer">
                      Inspect source evidence ↗
                    </a>
                  )}
                </article>
              ))}
            </div>

            {!!selectedScan.report && (
              <div className="ledger">
                <div className="sectionTitle">
                  <span>RULE LEDGER</span>
                  <small>{selectedScan.report.score_version}</small>
                </div>
                {selectedScan.report.dimensions.flatMap((dimension) =>
                  dimension.contributions.map((contribution) => (
                    <div className="ledgerRow" key={contribution.rule_id}>
                      <code>{contribution.rule_id}</code>
                      <span>{contribution.explanation}</span>
                      <b>{contribution.points}</b>
                    </div>
                  )),
                )}
              </div>
            )}
          </section>
        )}
      </section>
    </main>
  );
}
