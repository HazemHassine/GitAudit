"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Navigation } from "../../components/Navigation";
import {
  type Repository,
  type Scan,
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
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextRepository, nextHistory] = await Promise.all([
        request<Repository>(`/api/v1/repositories/${repositoryId}`),
        request<Scan[]>(`/api/v1/repositories/${repositoryId}/scans`),
      ]);
      setRepository(nextRepository);
      setHistory(nextHistory);
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
      setError(reason instanceof Error ? reason.message : "Repository scan failed");
      await load();
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

  const status = repository ? repositoryDisplayStatus(repository) : "unscanned";

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
