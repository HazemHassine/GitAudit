export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export type SignalStatus = "pass" | "fail" | "unknown" | "unavailable";
export type RepositoryStatus =
  | "unscanned"
  | "scanning"
  | "healthy"
  | "attention"
  | "degraded"
  | "scan_failed";
export type ScanStatus = "running" | "completed" | "partial" | "failed";
export type AssessmentStatus = "running" | "completed" | "failed";

export type Evidence = {
  source: string;
  summary: string;
  observed_at: string;
  url: string | null;
};

export type Signal = {
  dimension: string;
  key: string;
  status: SignalStatus;
  summary: string;
  evidence: Evidence;
  value: number | string | boolean | null;
};

export type Contribution = {
  rule_id: string;
  dimension: string;
  points: number;
  explanation: string;
  evidence_key: string;
};

export type Dimension = {
  dimension: string;
  score: number;
  status: SignalStatus;
  contributions: Contribution[];
};

export type Health = {
  score_version: string;
  overall_score: number;
  coverage_percent: number;
  repository_status: RepositoryStatus;
  dimensions: Dimension[];
  unavailable_dimensions: string[];
  status_reasons: string[];
};

export type Repository = {
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
  evidence_stale: boolean;
  latest_scan_status: ScanStatus | null;
  last_scan_error: string | null;
  monitoring_state: "active" | "excluded";
  health: Health | null;
};

export type Scan = {
  id: string;
  repository_id: string;
  started_at: string;
  completed_at: string | null;
  base_sha: string | null;
  status: ScanStatus;
  signals: Signal[];
  report: Health | null;
  source_failures: string[];
  error: string | null;
};

export type Account = {
  login: string;
  avatar_url: string | null;
  profile_url: string;
};

export type SyncStatus = {
  running: boolean;
  started_at: string | null;
  completed_at: string | null;
  discovered: number;
  monitored: number;
  queued: number;
  scanned: number;
  failed: number;
  error: string | null;
};

export type GitHubSettings = {
  configured: boolean;
  auth_mode: string;
  app_install_url: string | null;
  auto_scan_on_startup: boolean;
  auto_scan_interval_minutes: number;
  scan_stale_after_minutes: number;
};

export type AISettings = {
  configured: boolean;
  provider: string;
  model: string;
  workflow: string;
  prompt_version: string;
};

export type CurationRecommendation = {
  kind: "description" | "topics" | "readme" | "ci" | "archive_review";
  priority: "low" | "medium" | "high";
  title: string;
  rationale: string;
  evidence: string[];
  suggested_description: string | null;
  suggested_topics: string[];
  readme_plan: string[];
};

export type CurationAnalysis = {
  classification:
    | "active"
    | "portfolio"
    | "reference"
    | "experimental"
    | "stale"
    | "archive_candidate"
    | "insufficient_evidence";
  confidence: number;
  summary: string;
  strengths: string[];
  concerns: string[];
  recommendations: CurationRecommendation[];
};

export type CurationAssessment = {
  id: string;
  repository_id: string;
  scan_id: string | null;
  started_at: string;
  completed_at: string | null;
  status: AssessmentStatus;
  model: string;
  prompt_version: string;
  base_sha: string | null;
  evidence: Record<string, unknown>;
  analysis: CurationAnalysis | null;
  error: string | null;
};

export type ContributionDay = {
  date: string;
  count: number;
  level: number;
};

export type ContributionWeek = {
  days: ContributionDay[];
};

export type ContributionCalendar = {
  total: number;
  weeks: ContributionWeek[];
};

export type CommitWeek = {
  week: number;
  total: number;
  days: number[];
};

export type PunchCardEntry = {
  day: number;
  hour: number;
  commits: number;
};

export type RecentCommit = {
  sha: string;
  message: string;
  author: string;
  avatar_url: string | null;
  authored_at: string;
  repository: string;
  url: string;
};

export type GitHubEvent = {
  id: string;
  type: string;
  repo: string;
  created_at: string;
  summary: string;
};

export type DashboardStats = {
  total_repositories: number;
  public_count: number;
  private_count: number;
  languages: Record<string, number>;
  total_stars: number;
  health_distribution: Record<string, number>;
};

export type DashboardActivity = {
  contribution_calendar: ContributionCalendar;
  weekly_commits: CommitWeek[];
  punch_card: PunchCardEntry[];
  recent_commits: RecentCommit[];
  events: GitHubEvent[];
  fetched_at: string | null;
};

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed with HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function relativeTime(value: string | null): string {
  if (!value) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function label(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function repositoryDisplayStatus(repository: Repository): RepositoryStatus {
  if (repository.latest_scan_status === "running") return "scanning";
  if (repository.latest_scan_status === "failed") return "scan_failed";
  const status = repository.health?.repository_status ?? "unscanned";
  if (repository.evidence_stale && status === "healthy") return "attention";
  return status;
}
