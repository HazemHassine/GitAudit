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
    HEALTHY = "healthy"
    ATTENTION = "attention"
    DEGRADED = "degraded"
    SCAN_FAILED = "scan_failed"


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
    repository_status: RepositoryStatus
    dimensions: list[DimensionScore]
    unavailable_dimensions: list[HealthDimension]


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
    base_sha: str
    signals: list[HealthSignal]
    report: HealthReport
