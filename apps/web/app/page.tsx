"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Navigation } from "./components/Navigation";
import {
  type Account,
  type GitHubSettings,
  type Repository,
  type Scan,
  type SyncStatus,
  label,
  relativeTime,
  repositoryDisplayStatus,
  request,
} from "./lib/api";


export default function CommandCenter() {
  const [account, setAccount] = useState<Account | null>(null);
  const [settings, setSettings] = useState<GitHubSettings | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [latestScan, setLatestScan] = useState<Scan | null>(null);
  const [busy, setBusy] = useState<string | null>("loading");
  const [error, setError] = useState<string | null>(null);
  const [githubError, setGitHubError] = useState<string | null>(null);

  const loadLocal = useCallback(async (quiet = false) => {
    if (!quiet) setError(null);
    try {
      const [nextRepositories, nextSync, nextSettings] = await Promise.all([
        request<Repository[]>("/api/v1/repositories"),
        request<SyncStatus>("/api/v1/sync"),
        request<GitHubSettings>("/api/v1/settings/github"),
      ]);
      setRepositories(nextRepositories);
      setSync(nextSync);
      setSettings(nextSettings);
      setSelectedId((current) => {
        if (current && nextRepositories.some((item) => item.id === current)) return current;
        return nextRepositories[0]?.id ?? null;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load local repository data");
    } finally {
      if (!quiet) setBusy(null);
    }
  }, []);

  const loadIdentity = useCallback(async () => {
    try {
      setAccount(await request<Account>("/api/v1/github/account"));
      setGitHubError(null);
    } catch (reason) {
      setGitHubError(reason instanceof Error ? reason.message : "GitHub is unavailable");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadLocal();
      void loadIdentity();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadIdentity, loadLocal]);

  useEffect(() => {
    if (!sync?.running) return;
    const timer = window.setInterval(() => void loadLocal(true), 1500);
    return () => window.clearInterval(timer);
  }, [loadLocal, sync?.running]);

  const selected =
    repositories.find((repository) => repository.id === selectedId) ??
    repositories[0] ??
    null;

  useEffect(() => {
    if (!selected) return;
    let current = true;
    void request<Scan[]>(`/api/v1/repositories/${selected.id}/scans`)
      .then((history) => {
        if (current) setLatestScan(history[0] ?? null);
      })
      .catch(() => {
        if (current) setLatestScan(null);
      });
    return () => {
      current = false;
    };
  }, [selected]);

  async function syncAll(force = true) {
    setBusy("sync");
    setError(null);
    try {
      setSync(await request<SyncStatus>(`/api/v1/sync?force=${force}`, { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to start repository sync");
    } finally {
      setBusy(null);
    }
  }

  async function scan(repository: Repository) {
    setBusy(`scan:${repository.id}`);
    setError(null);
    try {
      await request(`/api/v1/repositories/${repository.id}/scans`, { method: "POST" });
      await loadLocal(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Repository scan failed");
      await loadLocal(true);
    } finally {
      setBusy(null);
    }
  }

  const health = selected?.health;
  const displayStatus = selected ? repositoryDisplayStatus(selected) : "unscanned";
  const counts = useMemo(
    () =>
      repositories.reduce(
        (result, repository) => {
          result[repositoryDisplayStatus(repository)] += 1;
          return result;
        },
        {
          healthy: 0,
          attention: 0,
          degraded: 0,
          unscanned: 0,
          scanning: 0,
          scan_failed: 0,
        },
      ),
    [repositories],
  );

  return (
    <main className="shell">
      <Navigation active="pulse" />

      <section className="workspace">
        <header>
          <div>
            <p className="eyebrow">COMMAND CENTER / PERSISTED GITHUB EVIDENCE</p>
            <h1>Repository pulse</h1>
          </div>
          <div className="observer">
            <span>READ ONLY</span>
            <b>
              <i className={githubError ? "offline" : ""} />{" "}
              {account ? `@${account.login}` : settings?.configured ? "GITHUB DEGRADED" : "SETUP REQUIRED"}
            </b>
          </div>
        </header>

        {error && (
          <div className="errorBanner" role="alert">
            <b>LOCAL DATA FAILED</b>
            <span>{error}</span>
            <button onClick={() => void loadLocal()}>Retry</button>
          </div>
        )}
        {githubError && (
          <div className="warningBanner" role="status">
            <b>GITHUB UNAVAILABLE</b>
            <span>{githubError}. Showing the last persisted observations.</span>
            <Link href="/settings">Connection settings</Link>
          </div>
        )}

        <div className="truthbar" aria-live="polite">
          <span>{repositories.length} monitored</span>
          <span>{counts.healthy} healthy</span>
          <span>{counts.attention + counts.degraded + counts.scan_failed} need attention</span>
          <span className="grow" />
          {sync?.running && (
            <span className="syncProgress">
              Scanning {sync.scanned + sync.failed}/{sync.queued}
            </span>
          )}
          <button disabled={busy !== null || sync?.running} onClick={() => void syncAll()}>
            {sync?.running ? "Syncing all…" : "Sync + scan all"}
          </button>
        </div>

        {!settings?.configured && busy !== "loading" && (
          <section className="setupCallout">
            <div>
              <p className="label">GITHUB CONNECTION REQUIRED</p>
              <h2>Connect once; every authorized repository is monitored automatically.</h2>
            </div>
            <Link className="primaryAction" href="/settings">
              Configure GitHub
            </Link>
          </section>
        )}

        {sync?.running && repositories.length === 0 && (
          <section className="setupCallout" aria-live="polite">
            <div>
              <p className="label">INITIAL INVENTORY</p>
              <h2>Discovering and scanning every authorized repository…</h2>
              <p>
                {sync.discovered
                  ? `${sync.monitored} repositories found; ${sync.scanned} scans complete.`
                  : "Reading the GitHub App installation inventory."}
              </p>
            </div>
          </section>
        )}

        <section className="hero" id="pulse">
          <div className="scoreBlock">
            <p className="label">
              PULSE / {selected ? `${selected.owner}/${selected.name}` : "NO REPOSITORY"}
            </p>
            <div className={`score ${!health ? "scoreUnknown" : ""}`}>
              {health ? health.overall_score : "—"}
              <small>{health ? "/100" : "UNSCANNED"}</small>
            </div>
            <div className={`status ${displayStatus}`}>{label(displayStatus)}</div>
            {health && (
              <div className="coverage">
                <span>Evidence coverage</span>
                <b>{health.coverage_percent}%</b>
                <i>
                  <em style={{ width: `${health.coverage_percent}%` }} />
                </i>
              </div>
            )}
            <p className="caption">
              {health
                ? `Known evidence scored with ${health.score_version}. Health is gated when required evidence is missing.`
                : "The automatic inventory will create the first evidence-backed snapshot."}
            </p>
            {health?.status_reasons.map((reason) => (
              <p className="statusReason" key={reason}>
                {reason}
              </p>
            ))}
            {selected?.evidence_stale && (
              <p className="statusReason">Evidence is stale and queued for refresh.</p>
            )}
          </div>
          <div className="dimensionBlock">
            <div className="sectionTitle">
              <span>HEALTH SIGNALS</span>
              <small>OBSERVATION → SCORE</small>
            </div>
            {(health?.dimensions ?? []).map((item) => (
              <div className="dimension" key={item.dimension}>
                <span>{label(item.dimension)}</span>
                <div className={`track ${item.status}`}>
                  <i style={{ width: item.contributions.length ? `${item.score}%` : "5%" }} />
                </div>
                <b className={item.status}>
                  {item.contributions.length ? item.score : item.status.toUpperCase()}
                </b>
                <span className="evidenceCount">{item.contributions.length}</span>
              </div>
            ))}
            {!health && (
              <div className="heroEmpty">
                <b>No health report yet</b>
                <span>Automatic scanning starts as soon as GitHub is configured.</span>
              </div>
            )}
          </div>
        </section>

        <section className="grid" id="repositories">
          <div className="panel repositories">
            <div className="sectionTitle">
              <span>REPOSITORIES</span>
              <small>{repositories.length} AUTO-MONITORED</small>
            </div>
            {repositories.length === 0 && !sync?.running && (
              <div className="panelEmpty">
                <b>No persisted repositories</b>
                <span>Configure GitHub or start a full inventory scan.</span>
              </div>
            )}
            {repositories.map((repository) => {
              const repositoryStatus = repositoryDisplayStatus(repository);
              return (
                <article
                  className={`repo ${repository.id === selected?.id ? "selected" : ""}`}
                  key={repository.id}
                >
                  <button
                    className="repoSelect"
                    aria-label={`Show ${repository.owner}/${repository.name} summary`}
                    onClick={() => setSelectedId(repository.id)}
                  >
                    <span className="repoPulse">
                      <i className={repositoryStatus} />
                    </span>
                    <span>
                      <span className="repoName">
                        {repository.owner} / <b>{repository.name}</b>
                      </span>
                      <small>
                        {repository.default_branch} · {repository.primary_language ?? "Unknown"} ·{" "}
                        {repository.default_branch_sha?.slice(0, 7) ?? "not scanned"}
                      </small>
                    </span>
                  </button>
                  <div className="miniScore">
                    <strong>{repository.health?.overall_score ?? "—"}</strong>
                    <small>{label(repositoryStatus)}</small>
                  </div>
                  <button
                    className="scanButton"
                    disabled={busy !== null || sync?.running}
                    onClick={() => void scan(repository)}
                  >
                    {busy === `scan:${repository.id}` ? "…" : "Scan"}
                  </button>
                  <Link className="detailLink" href={`/repositories/${repository.id}`}>
                    Report →
                  </Link>
                </article>
              );
            })}
          </div>

          <div className="panel trace" id="evidence">
            <div className="sectionTitle">
              <span>LATEST EVIDENCE</span>
              <small>{selected ? relativeTime(selected.last_scanned_at) : "NO SCAN"}</small>
            </div>
            {selected?.last_scan_error && (
              <div className="inlineError">{selected.last_scan_error}</div>
            )}
            {!latestScan?.signals.length && (
              <div className="panelEmpty">
                <b>No evidence collected</b>
                <span>A completed or partial scan will place source observations here.</span>
              </div>
            )}
            <ol>
              {latestScan?.signals.map((signal) => (
                <li className={signal.status} key={signal.key}>
                  <i />
                  <div>
                    <b>{signal.summary}</b>
                    <small>
                      {label(signal.dimension)} · {label(signal.status)} ·{" "}
                      {relativeTime(signal.evidence.observed_at)}
                    </small>
                    {signal.evidence.url && (
                      <a href={signal.evidence.url} target="_blank" rel="noreferrer">
                        Open source evidence ↗
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ol>
            {selected && (
              <Link className="panelAction" href={`/repositories/${selected.id}`}>
                Open scan history and comparison →
              </Link>
            )}
          </div>
        </section>

        <footer>
          <span>OSS MAINTAINER / TRUSTWORTHY SCANS</span>
          <span>Observe · Explain · Remember</span>
        </footer>
      </section>
    </main>
  );
}
