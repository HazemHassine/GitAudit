"use client";

import { useEffect, useState } from "react";

import {
  type JulesAuditArea,
  type JulesAuditSession,
  label,
  relativeTime,
  request,
} from "../lib/api";

const AUDIT_AREAS: JulesAuditArea[] = [
  "build",
  "coverage",
  "ci",
  "dependencies",
  "security",
  "deployment",
  "documentation",
  "maintenance",
];

export function JulesActivityFeed() {
  const [sessions, setSessions] = useState<JulesAuditSession[]>([]);
  const [area, setArea] = useState<JulesAuditArea>("build");
  const [focus, setFocus] = useState("");
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSessions = async (quiet = false) => {
    try {
      const data = await request<JulesAuditSession[]>("/api/v1/jules/sessions");
      setSessions(data);
      setError(null);
    } catch (reason) {
      if (!quiet) {
        setError(reason instanceof Error ? reason.message : "Unable to load Jules activity");
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadSessions(), 0);
    const timer = window.setInterval(() => void loadSessions(true), 15_000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, []);

  const prepareReview = async () => {
    setPreparing(true);
    setError(null);
    try {
      const session = await request<JulesAuditSession>("/api/v1/jules/sessions", {
        method: "POST",
        body: JSON.stringify({ audit_area: area, focus: focus || null, dry_run: true }),
      });
      setSessions((current) => [session, ...current.filter((item) => item.session_id !== session.session_id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to prepare Jules review");
    } finally {
      setPreparing(false);
    }
  };

  return (
    <section className="julesActivityFeed" aria-label="Jules audit activity">
      <div className="julesActivityHead">
        <div>
          <p className="label">JULES AUDIT CONTROL</p>
          <h2>One review interface for every audit area</h2>
          <p>
            Prepare a scoped prompt here, then review it before any live Jules request. This control only
            creates previews; it does not invoke Jules.
          </p>
        </div>
        <span className="julesProcessNote">Activity is retained for the current API process.</span>
      </div>

      <div className="julesControls">
        <label>
          <span>Audit area</span>
          <select value={area} onChange={(event) => setArea(event.target.value as JulesAuditArea)}>
            {AUDIT_AREAS.map((item) => (
              <option key={item} value={item}>{label(item)}</option>
            ))}
          </select>
        </label>
        <label className="julesFocus">
          <span>Review focus</span>
          <input
            value={focus}
            maxLength={500}
            onChange={(event) => setFocus(event.target.value)}
            placeholder="Optional scope, such as Docker cache layers"
          />
        </label>
        <button className="julesPrepare" disabled={preparing} onClick={prepareReview}>
          {preparing ? "Preparing…" : "Prepare review"}
        </button>
      </div>

      {error && <p className="inlineError">{error}</p>}
      {loading ? (
        <p className="julesEmpty">Loading activity…</p>
      ) : sessions.length === 0 ? (
        <p className="julesEmpty">No audit review has been prepared yet.</p>
      ) : (
        <ol className="julesSessionList">
          {sessions.map((session) => (
            <li key={session.session_id}>
              <div className="julesSessionSummary">
                <div>
                  <p className="label">{label(session.audit_area)} · {relativeTime(session.created_at)}</p>
                  <b>{session.plan_status ?? "Review session"}</b>
                  {session.focus && <span>{session.focus}</span>}
                </div>
                <span className={`status jules-${session.status}`}>{label(session.status)}</span>
              </div>
              <details>
                <summary>Review prompt and activity</summary>
                <pre>{session.prompt}</pre>
                <ul>
                  {session.activity.map((entry) => <li key={entry}>{entry}</li>)}
                </ul>
                {session.pull_request_url && <a href={session.pull_request_url}>Review pull request ↗</a>}
                {session.url && <a href={session.url}>Open Jules session ↗</a>}
              </details>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
