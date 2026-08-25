"use client";

import { useCallback, useEffect, useState } from "react";

import { Navigation } from "../components/Navigation";
import {
  type AISettings,
  type Account,
  type GitHubSettings,
  type SyncStatus,
  label,
  relativeTime,
  request,
} from "../lib/api";


export default function SettingsPage() {
  const [settings, setSettings] = useState<GitHubSettings | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [aiSettings, setAISettings] = useState<AISettings | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [settingsResult, syncResult, accountResult, aiResult] = await Promise.allSettled([
      request<GitHubSettings>("/api/v1/settings/github"),
      request<SyncStatus>("/api/v1/sync"),
      request<Account>("/api/v1/github/account"),
      request<AISettings>("/api/v1/settings/ai"),
    ]);
    if (settingsResult.status === "fulfilled") setSettings(settingsResult.value);
    if (syncResult.status === "fulfilled") setSync(syncResult.value);
    if (accountResult.status === "fulfilled") {
      setAccount(accountResult.value);
      setConnectionError(null);
    } else {
      setConnectionError(accountResult.reason instanceof Error ? accountResult.reason.message : "GitHub connection failed");
    }
    if (aiResult.status === "fulfilled") setAISettings(aiResult.value);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!sync?.running) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [load, sync?.running]);

  async function scanAll() {
    setBusy(true);
    try {
      setSync(await request<SyncStatus>("/api/v1/sync?force=true", { method: "POST" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <Navigation active="settings" />
      <section className="workspace settingsWorkspace">
        <header>
          <div>
            <p className="eyebrow">SETTINGS / GITHUB OBSERVER</p>
            <h1>Connection and automation</h1>
          </div>
          <div className={`connectionBadge ${settings?.configured && account ? "connected" : "disconnected"}`}>
            {settings?.configured && account ? `Connected as @${account.login}` : "Setup required"}
          </div>
        </header>

        {connectionError && (
          <div className="warningBanner" role="status">
            <b>CONNECTION CHECK</b>
            <span>{connectionError}</span>
          </div>
        )}

        <section className="settingsGrid">
          <article className="settingsCard primarySettings">
            <p className="label">RECOMMENDED / GITHUB APP</p>
            <h2>Least-privilege installation access</h2>
            <p>
              Install the app on the repositories you authorize. Installation tokens are short-lived
              and generated automatically; private keys and tokens are never returned to the browser.
            </p>
            <div className="permissionList">
              <span><b>Metadata</b> Read</span>
              <span><b>Contents</b> Read</span>
              <span><b>Actions</b> Read</span>
              <span><b>Checks</b> Read</span>
            </div>
            {settings?.app_install_url ? (
              <a className="primaryAction" href={settings.app_install_url} target="_blank" rel="noreferrer">
                Install or configure GitHub App ↗
              </a>
            ) : (
              <p className="configHint">
                Set <code>GITHUB_APP_SLUG</code> to expose the installation link here.
              </p>
            )}
            <div className="envBlock">
              <code>GITHUB_AUTH_MODE=app</code>
              <code>GITHUB_APP_ID=…</code>
              <code>GITHUB_INSTALLATION_ID=…</code>
              <code>GITHUB_APP_PRIVATE_KEY_PATH=…</code>
              <code>GITHUB_APP_SLUG=…</code>
            </div>
          </article>

          <article className="settingsCard">
            <p className="label">LOCAL FALLBACK / FINE-GRAINED TOKEN</p>
            <h2>Personal development connection</h2>
            <p>
              A fine-grained read-only token remains supported for local development. Limit its
              repository selection and grant Metadata, Contents, Actions, and Checks read access.
            </p>
            <div className="envBlock">
              <code>GITHUB_AUTH_MODE=token</code>
              <code>GITHUB_TOKEN=…</code>
            </div>
            <small>Current mode: {label(settings?.auth_mode ?? "loading")}</small>
          </article>

          <article className="settingsCard automationCard">
            <p className="label">AUTOMATIC INVENTORY</p>
            <h2>Every authorized repository, without manual selection</h2>
            <dl>
              <div><dt>Scan on API startup</dt><dd>{settings?.auto_scan_on_startup ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Stale after</dt><dd>{settings?.scan_stale_after_minutes ?? "—"} minutes</dd></div>
              <div><dt>Recurring interval</dt><dd>{settings?.auto_scan_interval_minutes ? `${settings.auto_scan_interval_minutes} minutes` : "Startup/manual"}</dd></div>
              <div><dt>Last inventory</dt><dd>{relativeTime(sync?.completed_at ?? null)}</dd></div>
            </dl>
            {sync?.running && (
              <p aria-live="polite">
                {sync.scanned + sync.failed}/{sync.queued} repositories processed; {sync.failed} failed.
              </p>
            )}
            <button disabled={busy || sync?.running || !settings?.configured} onClick={() => void scanAll()}>
              {sync?.running ? "Scanning every repository…" : "Discover + scan everything now"}
            </button>
          </article>

          <article className="settingsCard automationCard">
            <p className="label">AI PROFILE CURATOR / LANGGRAPH</p>
            <h2>Evidence-backed proposals, never automatic changes</h2>
            <p>
              The curation graph reviews persisted scan evidence, repository metadata, topics, and
              README content. Its structured recommendations are stored for review.
            </p>
            <dl>
              <div><dt>Provider</dt><dd>{label(aiSettings?.provider ?? "loading")}</dd></div>
              <div><dt>Configured</dt><dd>{aiSettings?.configured ? "Yes" : "No"}</dd></div>
              <div><dt>Model</dt><dd>{aiSettings?.model ?? "—"}</dd></div>
              <div><dt>Workflow</dt><dd>{label(aiSettings?.workflow ?? "langgraph")}</dd></div>
              <div><dt>Prompt</dt><dd>{aiSettings?.prompt_version ?? "—"}</dd></div>
            </dl>
            {!aiSettings?.configured && (
              <div className="envBlock">
                <code>OPENAI_API_KEY=…</code>
                <code>OPENAI_MODEL=gpt-5.4-mini</code>
              </div>
            )}
          </article>
        </section>

        <section className="settingsNote">
          <b>Configuration remains server-owned.</b>
          <span>
            Restart the API after editing <code>.env</code>. The UI exposes connection state but never
            reads or writes credentials.
          </span>
        </section>
      </section>
    </main>
  );
}
