from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SignalStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class HealthDimension(StrEnum):
    BUILD = "build"
    TESTS = "tests"
    CI = "ci"
    DEPENDENCIES = "dependencies"
    SECURITY = "security"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    MAINTENANCE = "maintenance"


class RepositoryStatus(StrEnum):
    UNSCANNED = "unscanned"
    SCANNING = "scanning"
    HEALTHY = "healthy"
    ATTENTION = "attention"
    DEGRADED = "degraded"
    SCAN_FAILED = "scan_failed"


class ScanStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class MonitoringState(StrEnum):
    ACTIVE = "active"
    EXCLUDED = "excluded"


class AssessmentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RelevanceClassification(StrEnum):
    ACTIVE = "active"
    PORTFOLIO = "portfolio"
    REFERENCE = "reference"
    EXPERIMENTAL = "experimental"
    STALE = "stale"
    ARCHIVE_CANDIDATE = "archive_candidate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendationKind(StrEnum):
    DESCRIPTION = "description"
    TOPICS = "topics"
    README = "readme"
    CI = "ci"
    ARCHIVE_REVIEW = "archive_review"


class RecommendationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceRef(BaseModel):
    source: str
    summary: str
    observed_at: datetime
    url: str | None = None


class HealthSignal(BaseModel):
    dimension: HealthDimension
    key: str
    status: SignalStatus
    summary: str
    evidence: EvidenceRef
    value: float | int | str | bool | None = None


class ScoreContribution(BaseModel):
    rule_id: str
    dimension: HealthDimension
    points: int
    explanation: str
    evidence_key: str


class DimensionScore(BaseModel):
    dimension: HealthDimension
    score: int = Field(ge=0, le=100)
    status: SignalStatus
    contributions: list[ScoreContribution]


class HealthReport(BaseModel):
    score_version: str
    overall_score: int = Field(ge=0, le=100)
    coverage_percent: int = Field(default=0, ge=0, le=100)
    repository_status: RepositoryStatus
    dimensions: list[DimensionScore]
    unavailable_dimensions: list[HealthDimension]
    status_reasons: list[str] = Field(default_factory=list)


class RepositorySummary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner: str
    name: str
    description: str | None = None
    default_branch: str = "main"
    primary_language: str | None = None
    private: bool = False
    html_url: str | None = None
    default_branch_sha: str | None = None
    last_commit_at: datetime | None = None
    last_scanned_at: datetime | None = None
    evidence_stale: bool = False
    latest_scan_status: ScanStatus | None = None
    last_scan_error: str | None = None
    monitoring_state: MonitoringState = MonitoringState.ACTIVE
    health: HealthReport | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class GitHubAccount(BaseModel):
    login: str
    avatar_url: str | None = None
    profile_url: str


class DiscoveredRepository(BaseModel):
    github_id: int
    owner: str
    name: str
    description: str | None = None
    default_branch: str
    primary_language: str | None = None
    private: bool
    html_url: str
    monitored: bool = False


class ConnectRepositoryRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")


class ScanSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    repository_id: UUID
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    base_sha: str | None = None
    status: ScanStatus = ScanStatus.COMPLETED
    signals: list[HealthSignal] = Field(default_factory=list)
    report: HealthReport | None = None
    source_failures: list[str] = Field(default_factory=list)
    error: str | None = None


class SyncStatus(BaseModel):
    running: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    discovered: int = 0
    monitored: int = 0
    queued: int = 0
    scanned: int = 0
    failed: int = 0
    error: str | None = None


class GitHubSettingsStatus(BaseModel):
    configured: bool
    auth_mode: str
    app_install_url: str | None = None
    auto_scan_on_startup: bool
    auto_scan_interval_minutes: int
    scan_stale_after_minutes: int


class AISettingsStatus(BaseModel):
    configured: bool
    provider: str = "openai"
    model: str
    workflow: str = "langgraph"
    prompt_version: str


class CurationRecommendation(BaseModel):
    kind: RecommendationKind
    priority: RecommendationPriority
    title: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    suggested_description: str | None = Field(default=None, max_length=350)
    suggested_topics: list[str] = Field(default_factory=list, max_length=12)
    readme_plan: list[str] = Field(default_factory=list, max_length=12)


class CurationAnalysis(BaseModel):
    classification: RelevanceClassification
    confidence: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=800)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    concerns: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[CurationRecommendation] = Field(default_factory=list, max_length=8)


class CurationAssessment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    repository_id: UUID
    scan_id: UUID | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: AssessmentStatus = AssessmentStatus.RUNNING
    model: str
    prompt_version: str
    base_sha: str | None = None
    evidence: dict[str, object] = Field(default_factory=dict)
    analysis: CurationAnalysis | None = None
    error: str | None = None


class ContributionDay(BaseModel):
    date: str
    count: int
    level: int = 0

class ContributionWeek(BaseModel):
    days: list[ContributionDay]

class ContributionCalendar(BaseModel):
    total: int = 0
    weeks: list[ContributionWeek] = Field(default_factory=list)

class CommitWeek(BaseModel):
    week: int
    total: int
    days: list[int] = Field(default_factory=list)

class PunchCardEntry(BaseModel):
    day: int
    hour: int
    commits: int

class RecentCommit(BaseModel):
    sha: str
    message: str
    author: str
    avatar_url: str | None = None
    authored_at: str
    repository: str
    url: str

class GitHubEvent(BaseModel):
    id: str
    type: str
    repo: str
    created_at: str
    summary: str

class DashboardStats(BaseModel):
    total_repositories: int = 0
    public_count: int = 0
    private_count: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    total_stars: int = 0
    health_distribution: dict[str, int] = Field(default_factory=dict)

class DashboardActivity(BaseModel):
    contribution_calendar: ContributionCalendar = Field(default_factory=ContributionCalendar)
    weekly_commits: list[CommitWeek] = Field(default_factory=list)
    punch_card: list[PunchCardEntry] = Field(default_factory=list)
    recent_commits: list[RecentCommit] = Field(default_factory=list)
    events: list[GitHubEvent] = Field(default_factory=list)
    fetched_at: str | None = None

class ReproductionPhase(StrEnum):
    QUEUED = "queued"
    FETCHING_LOGS = "fetching_logs"
    PREPARING_WORKSPACE = "preparing_workspace"
    DETECTING_STACK = "detecting_stack"
    EXECUTING_SANDBOX = "executing_sandbox"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReproductionEvent(BaseModel):
    timestamp: str
    phase: ReproductionPhase
    message: str
    level: str = "info"  # info, warning, error, stdout, stderr


class ReproductionRun(BaseModel):
    id: UUID
    repository_id: UUID
    commit_sha: str
    workflow_run_id: int | None = None
    job_id: int | None = None
    status: ScanStatus  # running, completed, failed, partial
    current_phase: ReproductionPhase
    detected_stack: str | None = None
    command: str | None = None
    exit_code: int | None = None
    events: list[ReproductionEvent] = Field(default_factory=list)
    output_logs: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


class CreateReproductionRequest(BaseModel):
    commit_sha: str | None = None  # defaults to latest default_branch_sha if None
    workflow_run_id: int | None = None
    job_id: int | None = None
    custom_command: str | None = None


class CoverageModule(BaseModel):
    name: str
    statements: int
    missed: int
    coverage_percent: float
    uncovered_lines: list[str] = Field(default_factory=list)


class JulesTestSession(BaseModel):
    session_id: str
    status: str = "idle"  # idle, queued, running, completed, failed, preview
    plan_status: str | None = None
    untested_cases: list[str] = Field(default_factory=list)
    pull_request_url: str | None = None
    logs: list[str] = Field(default_factory=list)


class CoverageSummary(BaseModel):
    status: str = "available"  # available, unavailable, error
    scope: str = "local"  # local, remote
    message: str | None = None
    coverage_percent: float | None = None
    threshold_percent: float = 80.0
    passed_threshold: bool | None = None
    total_statements: int = 0
    total_missed: int = 0
    tests_passed: int | None = None
    total_tests: int | None = None
    execution_time_seconds: float | None = None
    modules: list[CoverageModule] = Field(default_factory=list)
    jules_session: JulesTestSession | None = None


class GenerateTestsRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    focus_module: str | None = None
    target_coverage: float = 80.0
    dry_run: bool = False


class JulesCiSession(BaseModel):
    session_id: str = ""
    status: str = "idle"  # idle, queued, in_progress, completed, failed, preview
    plan_status: str | None = None
    bottlenecks: list[str] = Field(default_factory=list)
    flakiness_notes: list[str] = Field(default_factory=list)
    parallelization_suggestions: list[str] = Field(default_factory=list)
    pull_request_url: str | None = None
    url: str | None = None
    logs: list[str] = Field(default_factory=list)


class CiWorkflowSummary(BaseModel):
    name: str
    path: str
    lint_status: str = "valid"  # valid, invalid, unavailable, error
    lint_errors: list[str] = Field(default_factory=list)


class CiAuditSummary(BaseModel):
    actionlint_passed: bool | None = None
    total_workflows: int = 0
    workflows: list[CiWorkflowSummary] = Field(default_factory=list)
    actionlint_output: str = ""
    is_checking: bool = False
    last_run_status: str = "unavailable"  # success, failed, unavailable, error, attention
    jules_session: JulesCiSession | None = None
    scope: str = "local"  # local, remote
    message: str | None = None


class TriggerCiAnalysisRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    focus: str = "bottlenecks, flakiness, parallelization"
    dry_run: bool = True


class JulesAuditArea(StrEnum):
    BUILD = "build"
    COVERAGE = "coverage"
    CI = "ci"
    DEPENDENCIES = "dependencies"
    SECURITY = "security"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    MAINTENANCE = "maintenance"


class JulesSessionStatus(StrEnum):
    PREVIEW = "preview"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class CreateJulesSessionRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    audit_area: JulesAuditArea
    focus: str | None = Field(default=None, max_length=500)
    dry_run: bool = True


class JulesAuditSession(BaseModel):
    session_id: str
    audit_area: JulesAuditArea
    title: str
    status: JulesSessionStatus
    created_at: datetime
    focus: str | None = None
    plan_status: str | None = None
    activity: list[str] = Field(default_factory=list)
    prompt: str
    pull_request_url: str | None = None
    url: str | None = None
