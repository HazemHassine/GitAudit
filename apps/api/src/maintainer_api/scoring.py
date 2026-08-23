from collections import defaultdict
from dataclasses import dataclass

from .domain import (
    DimensionScore,
    HealthDimension,
    HealthReport,
    HealthSignal,
    RepositoryStatus,
    ScoreContribution,
    SignalStatus,
)


@dataclass(frozen=True)
class ScoringRule:
    signal_key: str
    pass_points: int
    fail_points: int
    description: str


RULES: dict[str, ScoringRule] = {
    "default_branch_ci": ScoringRule("default_branch_ci", 100, 0, "Latest default-branch CI succeeds"),
    "recent_ci_reliability": ScoringRule("recent_ci_reliability", 100, 0, "Recent CI success rate"),
    "readme_present": ScoringRule("readme_present", 100, 0, "README is present"),
}

DIMENSION_WEIGHTS: dict[HealthDimension, float] = {
    HealthDimension.CI: 0.5,
    HealthDimension.BUILD: 0.3,
    HealthDimension.DOCUMENTATION: 0.2,
}


def score_signals(signals: list[HealthSignal]) -> HealthReport:
    by_dimension: dict[HealthDimension, list[HealthSignal]] = defaultdict(list)
    for signal in signals:
        by_dimension[signal.dimension].append(signal)

    dimensions: list[DimensionScore] = []
    unavailable: list[HealthDimension] = []
    for dimension in HealthDimension:
        observed = by_dimension.get(dimension, [])
        scorable = [s for s in observed if s.status in {SignalStatus.PASS, SignalStatus.FAIL}]
        if not scorable:
            status = SignalStatus.UNAVAILABLE if any(
                s.status == SignalStatus.UNAVAILABLE for s in observed
            ) else SignalStatus.UNKNOWN
            unavailable.append(dimension)
            dimensions.append(DimensionScore(dimension=dimension, score=0, status=status, contributions=[]))
            continue

        contributions: list[ScoreContribution] = []
        for signal in scorable:
            rule = RULES[signal.key]
            if signal.key == "recent_ci_reliability" and isinstance(signal.value, (int, float)):
                points = round(max(0.0, min(1.0, float(signal.value))) * 100)
            else:
                points = rule.pass_points if signal.status == SignalStatus.PASS else rule.fail_points
            contributions.append(ScoreContribution(
                rule_id=f"m1.{signal.key}", dimension=dimension, points=points,
                explanation=f"{rule.description}: {signal.summary}", evidence_key=signal.key,
            ))
        score = round(sum(c.points for c in contributions) / len(contributions))
        dimensions.append(DimensionScore(
            dimension=dimension, score=score,
            status=SignalStatus.PASS if score >= 70 else SignalStatus.FAIL,
            contributions=contributions,
        ))

    weighted = [(d.score, DIMENSION_WEIGHTS[d.dimension]) for d in dimensions if d.dimension in DIMENSION_WEIGHTS and d.contributions]
    overall = round(sum(score * weight for score, weight in weighted) / sum(weight for _, weight in weighted)) if weighted else 0
    status = RepositoryStatus.HEALTHY if overall >= 85 else RepositoryStatus.ATTENTION if overall >= 60 else RepositoryStatus.DEGRADED
    return HealthReport(
        score_version="m1.v1", overall_score=overall, repository_status=status,
        dimensions=dimensions, unavailable_dimensions=unavailable,
    )

