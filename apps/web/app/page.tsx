"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

type Contribution = {
  rule_id: string;
  points: number;
  explanation: string;
  evidence_key: string;
};
type Dimension = {
  dimension: string;
  score: number;
  status: "pass" | "fail" | "unknown" | "unavailable";
  contributions: Contribution[];
};
type Health = {
  score_version: string;
  overall_score: number;
  repository_status: "healthy" | "attention" | "degraded" | "unscanned";
  dimensions: Dimension[];
  unavailable_dimensions: string[];
};
type Repository = {
  id: string;
  owner: string;
  name: string;
  description: string | null;
  default_branch: string;
  primary_language: string | null;
  private: boolean;
  html_url: string | null;
  default_branch_sha: string | null;
  last_commit_at: string | null;
  last_scanned_at: string | null;
  health: Health | null;
};
type DiscoveredRepository = Omit<Repository, "id" | "default_branch_sha" | "last_commit_at" | "last_scanned_at" | "health"> & {
  github_id: number;
  html_url: string;
  monitored: boolean;
};
type Account = { login: string; avatar_url: string | null; profile_url: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed with HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function relativeTime(value: string | null): string {
  if (!value) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function label(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function CommandCenter() {
  const [account, setAccount] = useState<Account | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [discovered, setDiscovered] = useState<DiscoveredRepository[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextAccount, nextRepositories, nextDiscovered] = await Promise.all([
        request<Account>("/api/v1/github/account"),
        request<Repository[]>("/api/v1/repositories"),
        request<DiscoveredRepository[]>("/api/v1/github/repositories"),
      ]);
      setAccount(nextAccount);
      setRepositories(nextRepositories);
      setDiscovered(nextDiscovered);
      setSelectedId((current) => current ?? nextRepositories[0]?.id ?? null);
      if (nextRepositories.length === 0) setShowDiscovery(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load GitHub repositories");
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const selected = repositories.find((repository) => repository.id === selectedId) ?? repositories[0] ?? null;
  const available = useMemo(() => discovered.filter((repository) => {
    const text = `${repository.owner}/${repository.name} ${repository.description ?? ""}`.toLowerCase();
    return !repository.monitored && text.includes(query.toLowerCase());
  }), [discovered, query]);

  async function monitor(repository: DiscoveredRepository) {
    const key = `monitor:${repository.github_id}`;
    setBusy(key); setError(null);
    try {
      const connected = await request<Repository>("/api/v1/repositories", {
        method: "POST", body: JSON.stringify({ owner: repository.owner, name: repository.name }),
      });
      await request(`/api/v1/repositories/${connected.id}/scans`, { method: "POST" });
      setSelectedId(connected.id);
      await load();
      setShowDiscovery(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to monitor repository");
    } finally { setBusy(null); }
  }

  async function scan(repository: Repository) {
    setBusy(`scan:${repository.id}`); setError(null);
    try {
      await request(`/api/v1/repositories/${repository.id}/scans`, { method: "POST" });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Repository scan failed");
    } finally { setBusy(null); }
  }

  const health = selected?.health;
  const score = health?.overall_score ?? 0;
  const unknownCount = health?.dimensions.filter((item) => item.status === "unknown" || item.status === "unavailable").length ?? 0;
  const contributions = health?.dimensions.flatMap((item) => item.contributions) ?? [];

  return (
    <main className="shell">
      <aside className="rail">
        <div className="mark" aria-label="OSS Maintainer">M<span>/</span></div>
        <nav aria-label="Primary"><a className="active" href="#pulse">Pulse</a><a href="#repositories">Repositories</a><a href="#evidence">Evidence</a><a href="#settings">Settings</a></nav>
        <div className="railFoot"><i /> observer online</div>
      </aside>

      <section className="workspace">
        <header>
          <div><p className="eyebrow">COMMAND CENTER / LIVE GITHUB DATA</p><h1>Repository pulse</h1></div>
          <div className="observer"><span>READ ONLY</span><b><i /> {account ? `@${account.login}` : "CONNECTING"}</b></div>
        </header>

        {error && <div className="errorBanner"><b>OBSERVATION FAILED</b><span>{error}</span><button onClick={() => void load()}>Retry</button></div>}

        <div className="truthbar">
          <span>{repositories.length} monitored</span><span>{discovered.length} accessible</span>
          <span>{unknownCount} dimensions unknown</span><span className="grow" />
          <button onClick={() => setShowDiscovery((value) => !value)}>+ Monitor repository</button>
        </div>

        {showDiscovery && (
          <section className="discovery" aria-label="Accessible GitHub repositories">
            <div className="discoveryHead"><div><p className="label">GITHUB / ACCESSIBLE REPOSITORIES</p><h2>Select what the maintainer should observe</h2></div><button className="close" onClick={() => setShowDiscovery(false)}>×</button></div>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter repositories…" aria-label="Filter repositories" />
            <div className="discoveryList">
              {busy === "loading" && <p className="empty">Reading repository access from GitHub…</p>}
              {!busy && available.length === 0 && <p className="empty">No unmonitored repositories match this filter.</p>}
              {available.map((repository) => (
                <article key={repository.github_id}>
                  <div><b>{repository.owner} / {repository.name}</b><p>{repository.description ?? "No description"}</p><small>{repository.private ? "PRIVATE" : "PUBLIC"} · {repository.primary_language ?? "Language unknown"} · {repository.default_branch}</small></div>
                  <button disabled={busy !== null} onClick={() => void monitor(repository)}>{busy === `monitor:${repository.github_id}` ? "Connecting…" : "Monitor + scan"}</button>
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="hero" id="pulse">
          <div className="scoreBlock">
            <p className="label">PULSE / {selected ? `${selected.owner}/${selected.name}` : "NO REPOSITORY"}</p>
            <div className={`score ${!health ? "scoreUnknown" : ""}`}>{health ? score : "—"}<small>{health ? "/100" : "UNSCANNED"}</small></div>
            <div className={`status ${health?.repository_status ?? "unscanned"}`}>{health ? label(health.repository_status) : "No observation"}</div>
            <p className="caption">{health ? <>Derived with scoring rules <code>{health.score_version}</code>. Unknown data does not count as healthy.</> : "Select a repository above to create the first evidence-backed health snapshot."}</p>
          </div>
          <div className="dimensionBlock">
            <div className="sectionTitle"><span>HEALTH SIGNALS</span><small>OBSERVATION → SCORE</small></div>
            {(health?.dimensions ?? []).map((item) => (
              <div className="dimension" key={item.dimension}>
                <span>{label(item.dimension)}</span><div className={`track ${item.status}`}><i style={{ width: item.contributions.length ? `${item.score}%` : "5%" }} /></div>
                <b className={item.status}>{item.contributions.length ? item.score : item.status.toUpperCase()}</b><span className="evidenceCount">{item.contributions.length}</span>
              </div>
            ))}
            {!health && <div className="heroEmpty"><b>No health report yet</b><span>Connect a repository and run its first scan.</span></div>}
          </div>
        </section>

        <section className="grid" id="repositories">
          <div className="panel repositories">
            <div className="sectionTitle"><span>REPOSITORIES</span><small>{repositories.length} MONITORED</small></div>
            {repositories.length === 0 && <div className="panelEmpty"><b>Your monitoring set is empty</b><span>The token works. Choose a repository from the GitHub list above.</span></div>}
            {repositories.map((repository) => (
              <article className={`repo ${repository.id === selected?.id ? "selected" : ""}`} key={repository.id} onClick={() => setSelectedId(repository.id)}>
                <div className="repoPulse"><i className={repository.health?.repository_status ?? "unscanned"} /></div>
                <div><p className="repoName">{repository.owner} / <b>{repository.name}</b></p><p>{repository.default_branch} <span>•</span> {repository.primary_language ?? "Unknown"} <span>•</span> {repository.default_branch_sha?.slice(0, 7) ?? "not scanned"}</p></div>
                <div className="miniScore"><strong>{repository.health?.overall_score ?? "—"}</strong><small>{repository.health?.repository_status.toUpperCase() ?? "UNSCANNED"}</small></div>
                <button className="scanButton" disabled={busy !== null} onClick={(event) => { event.stopPropagation(); void scan(repository); }}>{busy === `scan:${repository.id}` ? "…" : "Scan"}</button>
              </article>
            ))}
          </div>

          <div className="panel trace" id="evidence">
            <div className="sectionTitle"><span>EVIDENCE / SCORE LEDGER</span><small>{selected ? relativeTime(selected.last_scanned_at) : "NO SCAN"}</small></div>
            {contributions.length === 0 && <div className="panelEmpty"><b>No evidence ledger</b><span>A completed scan will put each scoring rule here.</span></div>}
            <ol>{contributions.map((item) => (
              <li className="done" key={item.rule_id}><i /><div><b>{item.explanation}</b><small>{item.rule_id} · evidence: {item.evidence_key}</small></div><time>{item.points}</time></li>
            ))}</ol>
          </div>
        </section>

        <footer><span>OSS MAINTAINER / MILESTONE 1</span><span>Observe · Explain · Remember</span></footer>
      </section>
    </main>
  );
}
