import { expect, test } from "@playwright/test";

const repoId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const repoRun = "33333333-3333-4333-8333-333333333333";
const version = "a".repeat(64);

test("restores audit evidence, approves exactly a displayed plan and supports mobile", async ({ page }) => {
  let approved = false;
  const decisions: unknown[] = [];
  const snapshot = () => ({ id: runId, created_at: "2026-09-12T12:00:00Z", status: "running", stopped: false, deep_review: false, force: false,
    summary: { total: 1, completed: 0, awaiting_approval: approved ? 0 : 1, blocked: 0, pr_ready: 0 },
    repositories: [{ id: repoRun, repository_id: repoId, repository: "acme/widgets", stage: approved ? "approved" : "awaiting_approval", base_sha: "abcdef0123456789", checks: [{ key: ".:test", area: "tests", status: "fail", output: "Expected dependency install to succeed", tool_version: "node 22" }, { key: "coverage-reports", area: "tests", status: "missing_configuration", output: "No coverage report" }], findings: [{ key: ".:test" }], validation: [], plan: { steps: [{ id: "1", title: "Fix dependency installation", description: "Repair the locked dependency and rerun tests." }] }, plan_version: version, approved_version: approved ? version : null, session_name: "sessions/fixture", session_purpose: "Repair evidenced failures", remote_state: "AWAITING_PLAN_APPROVAL", corrections: 0, message: "Plan ready for review", created_at: "2026-09-12T12:00:00Z", completed_at: null, pr_url: null }] });
  await page.route("http://localhost:8001/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/stream")) return route.fulfill({ contentType: "text/event-stream", body: `id: 1\nevent: audit\ndata: ${JSON.stringify({ id: 1, run_id: repoRun, kind: "check", created_at: "2026-09-12T12:01:00Z", data: { message: "actionlint: checking three workflows" } })}\n\n` });
    if (path.endsWith("/decision")) {
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      decisions.push(route.request().postDataJSON()); approved = true;
      return route.fulfill({ json: snapshot() });
    }
    let body: unknown = {};
    if (path === "/api/v1/auth/session") body = { authenticated: true };
    else if (path === "/api/v1/repositories") body = [{ id: repoId, owner: "acme", name: "widgets" }];
    else if (path.endsWith("/settings")) body = { repository_ids: [repoId] };
    else if (path.endsWith("/status")) body = { paused: false, worker_online: true, quota: { used: 1, reserved: 0, queued: 0, limit: 80, remaining: 79, next_available_at: null } };
    else if (path === "/api/v1/audits/runs") body = [snapshot()];
    else if (path.endsWith(runId)) body = snapshot();
    return route.fulfill({ json: body });
  });
  await page.goto(`/audits/runs/${runId}`);
  await expect(page.getByRole("heading", { name: "Audits." })).toBeVisible();
  await page.locator(".auditRepo > summary").click();
  await expect(page.getByRole("heading", { name: "Repair plan" })).toBeVisible();
  await expect(page.getByText("missing configuration", { exact: true })).toBeVisible();
  await page.reload();
  await page.locator(".auditRepo > summary").click();
  await expect(page.getByText("Fix dependency installation", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve this plan" }).click();
  await expect(page.locator(".auditBadge")).toHaveText("approved");
  expect(decisions).toEqual([{ version, decision: "approve", feedback: "" }]);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("link", { name: "Audits", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: "/tmp/gitaudit-audits-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.screenshot({ path: "/tmp/gitaudit-audits-desktop.png", fullPage: true });
});

test("requires owner login before displaying audit evidence", async ({ page }) => {
  await page.route("http://localhost:8001/**", route => route.fulfill({ json: { authenticated: false } }));
  await page.goto("/audits");
  await expect(page.getByRole("heading", { name: "Sign in to run audits" })).toBeVisible();
  await expect(page.getByLabel("Owner password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run checks" })).toHaveCount(0);
});
