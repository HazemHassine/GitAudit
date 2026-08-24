import { expect, test } from "@playwright/test";


const health = {
  score_version: "m1.v1.1",
  overall_score: 93,
  coverage_percent: 100,
  repository_status: "healthy",
  unavailable_dimensions: ["build", "tests", "dependencies", "security", "deployment", "maintenance"],
  status_reasons: [],
  dimensions: [
    {
      dimension: "ci",
      score: 90,
      status: "pass",
      contributions: [
        {
          rule_id: "m1.default_branch_ci",
          dimension: "ci",
          points: 100,
          explanation: "All checks passed",
          evidence_key: "default_branch_ci",
        },
        {
          rule_id: "m1.recent_ci_reliability",
          dimension: "ci",
          points: 80,
          explanation: "Four of five passed",
          evidence_key: "recent_ci_reliability",
        },
      ],
    },
    {
      dimension: "documentation",
      score: 100,
      status: "pass",
      contributions: [
        {
          rule_id: "m1.readme_present",
          dimension: "documentation",
          points: 100,
          explanation: "README found",
          evidence_key: "readme_present",
        },
      ],
    },
  ],
};

const repository = {
  id: "11111111-1111-4111-8111-111111111111",
  owner: "acme",
  name: "widgets",
  description: "Widget library",
  default_branch: "main",
  primary_language: "TypeScript",
  private: false,
  html_url: "https://github.com/acme/widgets",
  default_branch_sha: "abcdef1234567890",
  last_commit_at: "2026-08-24T12:00:00Z",
  last_scanned_at: "2026-08-24T12:01:00Z",
  evidence_stale: false,
  latest_scan_status: "completed",
  last_scan_error: null,
  monitoring_state: "active",
  health,
};

const scan = {
  id: "22222222-2222-4222-8222-222222222222",
  repository_id: repository.id,
  started_at: "2026-08-24T12:00:30Z",
  completed_at: "2026-08-24T12:01:00Z",
  base_sha: "abcdef1234567890",
  status: "completed",
  source_failures: [],
  error: null,
  report: health,
  signals: [
    {
      dimension: "ci",
      key: "default_branch_ci",
      status: "pass",
      summary: "All 4 checks passed for commit abcdef1",
      value: 0,
      evidence: {
        source: "github://acme/widgets/commits/abcdef1234567890/checks",
        summary: "All checks passed",
        observed_at: "2026-08-24T12:00:40Z",
        url: "https://github.com/acme/widgets/commit/abcdef1234567890/checks",
      },
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("http://localhost:8001/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown;
    if (path === "/api/v1/repositories") body = [repository];
    else if (path === `/api/v1/repositories/${repository.id}`) body = repository;
    else if (path === `/api/v1/repositories/${repository.id}/scans`) body = [scan];
    else if (path === "/api/v1/github/account") {
      body = { login: "maintainer", avatar_url: null, profile_url: "https://github.com/maintainer" };
    } else if (path === "/api/v1/settings/github") {
      body = {
        configured: true,
        auth_mode: "app",
        app_install_url: "https://github.com/apps/oss-maintainer/installations/new",
        auto_scan_on_startup: true,
        auto_scan_interval_minutes: 0,
        scan_stale_after_minutes: 360,
      };
    } else if (path === "/api/v1/sync") {
      body = {
        running: false,
        started_at: null,
        completed_at: "2026-08-24T12:01:00Z",
        discovered: 1,
        monitored: 1,
        queued: 1,
        scanned: 1,
        failed: 0,
        error: null,
      };
    } else {
      return route.fulfill({ status: 404, json: { detail: "Not found in browser fixture" } });
    }
    await route.fulfill({ status: 200, json: body });
  });
});

test("shows persisted health and drills into source-linked scan history", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Repository pulse" })).toBeVisible();
  await expect(page.getByText("93", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Evidence coverage")).toBeVisible();
  await page.getByRole("link", { name: "Report →" }).click();
  await expect(page.getByRole("heading", { name: "acme/widgets" })).toBeVisible();
  await expect(page.getByText("LATEST VS PREVIOUS")).toBeVisible();
  await expect(page.getByRole("link", { name: "Inspect source evidence ↗" })).toHaveAttribute(
    "href",
    /github\.com\/acme\/widgets\/commit/,
  );
});
