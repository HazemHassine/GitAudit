"use client";

import { useState } from "react";
import { request } from "../lib/api";

export function OwnerLogin({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return <form className="auditLogin panel" onSubmit={async (e) => {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await request("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ password }) });
      setPassword(""); onLogin();
    } catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
    finally { setBusy(false); }
  }}>
    <p className="eyebrow">YOUR WORKSPACE</p>
    <h2>Sign in to run audits</h2>
    <p>Use the owner password configured for your local GitAudit installation.</p>
    <label htmlFor="owner-password">Owner password</label>
    <input id="owner-password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
    <button className="auditPrimary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
