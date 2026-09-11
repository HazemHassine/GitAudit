"""Shared, review-oriented prompts for every Jules audit area.

The API and the manually dispatched GitHub workflow import these definitions so
an audit area has one prompt and one set of safety constraints.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class JulesAuditDefinition:
    title: str
    objective: str
    review_targets: tuple[str, ...]


JULES_AUDIT_DEFINITIONS: dict[str, JulesAuditDefinition] = {
    "build": JulesAuditDefinition(
        title="Build system",
        objective="Review build reliability, cache efficiency, and bundle size without weakening checks.",
        review_targets=(
            "apps/web/next.config.ts and bundle budgets",
            "apps/api Dockerfile wheel build and dependency layers",
            "apps/web Dockerfile runtime image and cache layers",
        ),
    ),
    "coverage": JulesAuditDefinition(
        title="Test coverage & quality",
        objective="Identify meaningful uncovered behavior and propose focused tests that preserve existing contracts.",
        review_targets=(
            "apps/api/src/maintainer_api/curation.py error handling",
            "apps/api/src/maintainer_api/github.py rate-limit handling",
            "apps/api/src/maintainer_api/reproduction.py cancellation paths",
        ),
    ),
    "ci": JulesAuditDefinition(
        title="CI pipelines",
        objective="Review workflow reliability, useful parallelism, and failure diagnosis without masking failures.",
        review_targets=(
            ".github/workflows and actionlint configuration",
            "Makefile validation targets and dependency caches",
            "test, build, and security workflow sequencing",
        ),
    ),
    "dependencies": JulesAuditDefinition(
        title="Dependencies",
        objective="Identify unused, vulnerable, or unnecessarily heavy dependencies and safe upgrade paths.",
        review_targets=(
            ".github/dependabot.yml",
            "apps/api/pyproject.toml imports and dependency graph",
            "apps/web/package.json and production dependency audit",
        ),
    ),
    "security": JulesAuditDefinition(
        title="Security",
        objective="Review trust boundaries, authorization, secret handling, and command isolation; report evidence-backed findings only.",
        review_targets=(
            "maintainer_api/github.py authentication and token handling",
            "maintainer_api/curation.py untrusted content boundaries",
            "maintainer_api/reproduction.py command isolation",
        ),
    ),
    "deployment": JulesAuditDefinition(
        title="Deployment configuration",
        objective="Review container least privilege, configuration validation, graceful shutdown, and deployment resilience.",
        review_targets=(
            "docker-compose.yml health checks and environment settings",
            "apps/api/Dockerfile user and entrypoint",
            "apps/web/Dockerfile runtime configuration",
        ),
    ),
    "documentation": JulesAuditDefinition(
        title="Documentation",
        objective="Review API and architecture documentation for accuracy, discoverability, and synchronization with source code.",
        review_targets=(
            "docs/openapi.json and scripts/export_openapi.py",
            "README.md setup and validation instructions",
            "public API docstrings and link-check coverage",
        ),
    ),
    "maintenance": JulesAuditDefinition(
        title="Maintenance & refactoring",
        objective="Identify measurable complexity and cohesion improvements while keeping refactors small and reviewable.",
        review_targets=(
            "maintainer_api/service.py module boundaries",
            "ruff complexity and formatting results",
            "repeated API and UI patterns suitable for extraction",
        ),
    ),
}


def get_jules_audit_definition(audit_area: str) -> JulesAuditDefinition:
    return JULES_AUDIT_DEFINITIONS[audit_area]


def build_jules_prompt(audit_area: str, focus: str | None = None) -> str:
    """Return the shared, constrained prompt for an audit-area review."""
    definition = get_jules_audit_definition(audit_area)
    focus_line = focus.strip() if focus and focus.strip() else "Use the review targets below."
    targets = "\n".join(f"- {target}" for target in definition.review_targets)
    return (
        f"You are reviewing the GitAudit repository for the {definition.title} audit area.\n\n"
        f"Objective: {definition.objective}\n"
        f"Requested focus: {focus_line}\n\n"
        f"Review targets:\n{targets}\n\n"
        "First produce an evidence-backed plan. Do not claim a check passed unless you ran it and "
        "observed the result. Keep changes minimal, preserve the existing public API, and create a "
        "pull request only after the plan is approved and the relevant deterministic checks pass."
    )
