from datetime import UTC, datetime

from maintainer_api.domain import (
    EvidenceRef,
    HealthDimension,
    HealthSignal,
    RepositoryStatus,
    SignalStatus,
)
from maintainer_api.scoring import score_signals


def signal(dimension: HealthDimension, key: str, status: SignalStatus, value=None) -> HealthSignal:
    return HealthSignal(
        dimension=dimension, key=key, status=status, value=value, summary="fixture observation",
        evidence=EvidenceRef(source="test", summary="fixture", observed_at=datetime.now(UTC)),
    )


def test_score_is_deterministic_and_explainable() -> None:
    report = score_signals([
        signal(HealthDimension.CI, "default_branch_ci", SignalStatus.PASS),
        signal(HealthDimension.CI, "recent_ci_reliability", SignalStatus.PASS, 0.8),
        signal(HealthDimension.DOCUMENTATION, "readme_present", SignalStatus.FAIL),
    ])

    # Observed dimensions are reweighted to avoid treating unknown dimensions as zero.
    assert report.overall_score == 64
    assert report.repository_status == RepositoryStatus.ATTENTION
    ci = next(item for item in report.dimensions if item.dimension == HealthDimension.CI)
    assert ci.score == 90
    assert [item.rule_id for item in ci.contributions] == ["m1.default_branch_ci", "m1.recent_ci_reliability"]


def test_unknown_and_unavailable_are_not_scored_as_healthy() -> None:
    report = score_signals([
        signal(HealthDimension.SECURITY, "ignored", SignalStatus.UNAVAILABLE),
    ])

    assert report.overall_score == 0
    assert report.repository_status == RepositoryStatus.DEGRADED
    security = next(item for item in report.dimensions if item.dimension == HealthDimension.SECURITY)
    assert security.status == SignalStatus.UNAVAILABLE
    assert security.contributions == []
