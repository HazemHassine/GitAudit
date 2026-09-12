"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { getApiUrl, type Repository, request } from "../lib/api";
import type { AuditSnapshot, RepositoryAuditResult } from "../lib/audit-types";
import { Navigation } from "./Navigation";
import { OwnerLogin } from "./OwnerLogin";

type WorkerStatus = { paused: boolean; worker_online: boolean; quota: { used: number; reserved: number; remaining: number; limit: number; queued: number; next_available_at: string | null; provider_retry_at: string | null } };
type AuditEvent = { id: number; run_id: string; kind: string; created_at: string; data: Record<string, unknown> };
type CheckResult = { key: string; area: string; status: string; output: string; tool_version?: string; cached?: boolean };
const terminal = new Set(["completed", "partial", "blocked", "rejected", "stopped", "pr_ready"]);
const words = (value: string) => value.replaceAll("_", " ");
const message = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Try again.";

export function AuditsDashboard({ runId }: { runId?: string }) {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [runs, setRuns] = useState<AuditSnapshot[]>([]);
  const [run, setRun] = useState<AuditSnapshot | null>(null);
  const [status, setStatus] = useState<WorkerStatus | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [deep, setDeep] = useState(false);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plans, setPlans] = useState<string[]>([]);
  const pendingKey = useRef<{ body: string; key: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const auth = await request<{ authenticated: boolean }>("/api/v1/auth/session");
      setSignedIn(auth.authenticated);
      if (!auth.authenticated) return;
      const [repositoryList, settings, worker, history] = await Promise.all([
        request<Repository[]>("/api/v1/repositories"), request<{ repository_ids: string[] }>("/api/v1/audits/settings"),
        request<WorkerStatus>("/api/v1/audits/status"), request<AuditSnapshot[]>("/api/v1/audits/runs"),
      ]);
      setRepos(repositoryList); setSelected(settings.repository_ids); setStatus(worker); setRuns(history);
      if (runId) setRun(await request<AuditSnapshot>(`/api/v1/audits/runs/${runId}`));
      setError(null);
    } catch (err) { setError(message(err)); }
  }, [runId]);

  const refresh = useCallback(async () => {
    try {
      if (runId) setRun(await request<AuditSnapshot>(`/api/v1/audits/runs/${runId}`));
      setStatus(await request<WorkerStatus>("/api/v1/audits/status"));
    } catch (err) { setError(message(err)); }
  }, [runId]);

  useEffect(() => { const timer = setTimeout(() => void load(), 0); return () => clearTimeout(timer); }, [load]);
  useEffect(() => {
    if (!signedIn) return;
    const poll = setInterval(() => void refresh(), 5000);
    if (!runId) return () => clearInterval(poll);
    const stream = new EventSource(`${getApiUrl()}/api/v1/audits/runs/${runId}/stream`, { withCredentials: true });
    stream.addEventListener("audit", e => {
      const activity: AuditEvent = JSON.parse(e.data);
      setEvents(previous => previous.some(x => x.id === activity.id) ? previous : [...previous, activity].slice(-300));
      void refresh();
    });
    // EventSource reconnects with Last-Event-ID; polling keeps state usable through proxies.
    return () => { clearInterval(poll); stream.close(); };
  }, [runId, signedIn, refresh]);

  async function action(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); await refresh(); } catch (err) { setError(message(err)); }
    finally { setBusy(false); }
  }
  async function start() {
    const body = JSON.stringify({ repository_ids: [...selected].sort(), deep_review: deep, force });
    if (pendingKey.current?.body !== body) pendingKey.current = { body, key: crypto.randomUUID() };
    const created = await request<AuditSnapshot>("/api/v1/audits/runs", { method: "POST", body, headers: { "Idempotency-Key": pendingKey.current.key } });
    router.push(`/audits/runs/${created.id}`);
  }
  async function decision(repo: RepositoryAuditResult, value: "approve" | "reject" | "revise", feedback = "") {
    await request(`/api/v1/audits/repositories/${repo.id}/decision`, {
      method: "POST", headers: { "Idempotency-Key": `${repo.id}-${repo.plan_version}-${value}-${feedback ? await hash(feedback) : "none"}` },
      body: JSON.stringify({ version: repo.plan_version, decision: value, feedback }),
    });
  }
  const ready = run?.repositories.filter(repo => repo.stage === "awaiting_approval") ?? [];
  const disabled = busy || !!run?.stopped || !!status?.paused;
  return <div className="shell"><Navigation active="audits" /><main className="workspace auditWorkspace">
    <header><div><p className="eyebrow">GITAUDIT / REPOSITORY OPERATIONS</p><h1>Audits<span className="auditDot">.</span></h1></div>
      <div className="auditConnection"><i className={status?.worker_online ? "online" : ""} />{status?.worker_online ? "Worker connected" : "Worker offline"}
        {signedIn && <button onClick={() => void action(async () => { await request("/api/v1/auth/logout", { method: "POST" }); setSignedIn(false); })}>Sign out</button>}</div></header>
    <p className="auditIntro">Check the evidence. Approve a plan. Review one pull request.</p>
    {error && <div role="alert" className="auditError">{error}<button onClick={() => void load()}>Retry</button></div>}
    {signedIn === null && <p role="status">Connecting to your workspace…</p>}
    {signedIn === false && <OwnerLogin onLogin={() => void load()} />}
    {signedIn && <>
      <section className="auditControl" aria-label="Audit controls">
        <div className="auditSelection"><details><summary>{selected.length} repositories selected</summary>
          <fieldset><legend>Repositories to check</legend>{repos.length === 0 && <p>Connect repositories from the overview to get started.</p>}
            {repos.map(repo => <label key={repo.id}><input type="checkbox" checked={selected.includes(repo.id)} onChange={e => {
              const next = e.target.checked ? [...selected, repo.id] : selected.filter(id => id !== repo.id);
              setSelected(next); void request("/api/v1/audits/settings", { method: "PUT", body: JSON.stringify({ repository_ids: next }) }).catch(err => setError(message(err)));
            }} />{repo.owner}/{repo.name}</label>)}
          </fieldset></details>
          <div className="auditOptions"><label><input type="checkbox" checked={deep} onChange={e => setDeep(e.target.checked)} />Deep review</label>
            <label><input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} />Force recheck</label></div>
        </div>
        <button className="auditPrimary" disabled={busy || selected.length === 0 || status?.paused} onClick={() => void action(start)}>Run checks <span aria-hidden>↗</span></button>
        <div className="auditBudget"><strong>{status?.quota.used ?? "—"}<span> / {status?.quota.limit ?? 80}</span></strong><small>new Jules sessions · rolling 24h</small>
          <small>{status?.quota.reserved ?? 0} reserved · {status?.quota.queued ?? 0} queued</small>
          {status?.quota.next_available_at && <small>Next slot: {new Date(status.quota.next_available_at).toLocaleString()}</small>}
        </div>
        <button className="auditSecondary" disabled={busy} onClick={() => void action(() => request(`/api/v1/audits/queue/${status?.paused ? "resume" : "pause"}`, { method: "POST" }))}>{status?.paused ? "Resume queue" : "Pause queue"}</button>
      </section>
      {!status?.worker_online && <p className="auditNotice">The worker is offline. Runs stay saved and queued until it reconnects.</p>}
      {status?.paused && <p className="auditNotice">Queue paused. Remote activity is still tracked; new approvals and publication are paused.</p>}
      {run ? <>
        <div className="auditRunHeading"><div><p className="eyebrow">RUN / {run.id.slice(0, 8)}</p><h2>{run.stopped ? "Run stopped" : run.status === "completed" ? "Checks recorded" : "Repository check in progress"}</h2></div>
          {!run.stopped && run.status !== "completed" && <button className="auditSecondary" disabled={busy} onClick={() => void action(() => request(`/api/v1/audits/runs/${run.id}/stop`, { method: "POST" }))}>Stop run</button>}</div>
        <section className="auditSummary" aria-label="Run summary">{[["Completed", run.summary.completed], ["Awaiting approval", run.summary.awaiting_approval], ["Blocked", run.summary.blocked], ["PRs ready", run.summary.pr_ready]].map(([name, count]) => <div key={name}><strong>{count}</strong><span>{name}</span></div>)}</section>
        <ol className="auditStages" aria-label="Workflow stages"><li>01 / Evidence</li><li>02 / Checks</li><li>03 / Plan approval</li><li>04 / Validation</li><li>05 / Pull request</li></ol>
        {ready.length > 0 && <div className="auditApprovalBar"><span>{ready.length} real plans awaiting review</span><button className="auditPrimary" disabled={disabled || plans.length === 0} onClick={() => void action(async () => {
          for (const repo of ready.filter(r => plans.includes(`${r.id}:${r.plan_version}`))) await decision(repo, "approve");
          setPlans([]);
        })}>Approve selected ({plans.length})</button></div>}
        <section aria-label="Repository results" className="auditResults">
          <div className="auditTableHead"><span>Repository / evidence</span><span>Current stage</span><span>Findings</span><span>Elapsed</span></div>
          {run.repositories.map(repo => <RepositoryRow key={repo.id} repo={repo} events={events.filter(e => e.run_id === repo.id)} disabled={disabled}
            selected={plans.includes(`${repo.id}:${repo.plan_version}`)} select={checked => setPlans(previous => checked ? [...previous, `${repo.id}:${repo.plan_version}`] : previous.filter(id => id !== `${repo.id}:${repo.plan_version}`))}
            decision={(value, feedback) => action(() => decision(repo, value, feedback))}
            retry={() => action(async () => { const retried = await request<AuditSnapshot>(`/api/v1/audits/repositories/${repo.id}/retry`, { method: "POST", headers: { "Idempotency-Key": `retry-${repo.id}` } }); router.push(`/audits/runs/${retried.id}`); })} />)}
        </section>
      </> : <section className="auditEmpty"><span aria-hidden>↗</span><h2>A clear path from finding to fix.</h2><p>Select repositories and run their own checks. Passing repositories receive a report. Repairs wait for your approval.</p></section>}
      <section className="auditHistory"><h2>Run history</h2>{runs.length === 0 ? <p>No runs yet. Your first audit will appear here.</p> : runs.map(item => <Link key={item.id} href={`/audits/runs/${item.id}`}><span>{new Date(item.created_at).toLocaleString()}</span><code>{item.id.slice(0, 8)}</code><span>{item.summary.completed}/{item.summary.total} completed</span><b>{words(item.status)}</b></Link>)}</section>
    </>}
  </main></div>;
}

function RepositoryRow({ repo, events, disabled, selected, select, decision, retry }: {
  repo: RepositoryAuditResult; events: AuditEvent[]; disabled: boolean; selected: boolean; select: (checked: boolean) => void;
  decision: (value: "approve" | "reject" | "revise", feedback?: string) => Promise<void>; retry: () => Promise<void>;
}) {
  const [feedback, setFeedback] = useState("");
  const [clock, setClock] = useState(0);
  useEffect(() => { const update = () => setClock(Date.now()); const timer = setInterval(update, 1000); return () => clearInterval(timer); }, []);
  const elapsed = Math.max(0, Math.floor(((repo.completed_at ? Date.parse(repo.completed_at) : clock || Date.parse(repo.created_at)) - Date.parse(repo.created_at)) / 1000));
  const checks = repo.checks as unknown as CheckResult[];
  const validation = repo.validation as unknown as CheckResult[];
  const steps = (repo.plan?.steps ?? []) as { id: string; title: string; description: string }[];
  return <details className="auditRepo">
    <summary><div><strong>{repo.repository}</strong><small>{repo.base_sha?.slice(0, 12) ?? "Resolving commit"} · {repo.session_purpose}</small></div>
      <span className={`auditBadge stage-${repo.stage}`}>{words(repo.stage)}</span><span>{repo.findings.length}</span><time>{Math.floor(elapsed / 60)}m {elapsed % 60}s</time></summary>
    <div className="auditDetail">
      {repo.message && <p role="status" className="auditNotice">{repo.message}</p>}
      <CheckList title="Deterministic checks" checks={checks} />
      {repo.plan && <section className="auditPlan"><p className="eyebrow">JULES PROPOSAL · VERSION {repo.plan_version?.slice(0, 8)}</p><h3>Repair plan</h3>
        <ol>{steps.map(step => <li key={step.id}><strong>{step.title}</strong><p>{step.description}</p></li>)}</ol>
        <p>Scope: evidenced failures, relevant tests, and small documentation/configuration corrections. Validation reruns the repository&apos;s checks.</p>
        {repo.stage === "awaiting_approval" && <><label><input type="checkbox" checked={selected} disabled={disabled} onChange={e => select(e.target.checked)} />Select this plan for approval</label>
          <div className="auditPlanActions"><button className="auditPrimary" disabled={disabled} onClick={() => void decision("approve")}>Approve this plan</button><button className="auditSecondary" disabled={disabled} onClick={() => void decision("reject")}>Reject</button></div>
          <label htmlFor={`revision-${repo.id}`}>Request a revision</label><textarea id={`revision-${repo.id}`} value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="Describe what should change in this plan" />
          <button className="auditSecondary" disabled={disabled || !feedback.trim()} onClick={() => void decision("revise", feedback)}>Send revision request</button></>}
      </section>}
      <section><h3>Recorded activity</h3>{events.length === 0 ? <p>Waiting for recorded events…</p> : <ol className="auditActivity">{events.slice(-15).map(e => <li key={e.id}><time>{new Date(e.created_at).toLocaleTimeString()}</time><span>{String(e.data.message ?? e.data.description ?? e.kind)}</span></li>)}</ol>}
        <details><summary>Raw event evidence</summary><pre>{JSON.stringify(events, null, 2)}</pre></details>
      </section>
      {validation.length > 0 && <CheckList title="Independent validation" checks={validation} />}
      {repo.session_name && <a href={`https://jules.google.com/session/${repo.session_name.split("/").pop()}`} target="_blank" rel="noreferrer">Open Jules session ↗</a>}
      {repo.pr_url && <a className="auditPrimary" href={repo.pr_url} target="_blank" rel="noreferrer">Review repository pull request ↗</a>}
      {terminal.has(repo.stage) && repo.stage !== "pr_ready" && <button className="auditSecondary" disabled={disabled} onClick={() => void retry()}>Retry repository</button>}
    </div>
  </details>;
}

function CheckList({ title, checks }: { title: string; checks: CheckResult[] }) {
  return <section><h3>{title} <small>{checks.filter(c => c.status === "pass").length}/{checks.length} passed</small></h3>
    {checks.length === 0 ? <p>Checks have not completed yet.</p> : checks.map(check => <details className="auditCheck" key={check.key}><summary><span>{check.key}</span><b>{words(check.status)}{check.cached ? " · cached" : ""}</b></summary><small>{check.tool_version}</small><pre>{check.output || "No output recorded."}</pre></details>)}
  </section>;
}

async function hash(value: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}
