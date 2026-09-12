"""Transactional audit commands shared by UI, CLI and compatibility routes."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit_checks import digest
from .config import Settings
from .database import (
    AuditApprovalRecord,
    AuditBatchRecord,
    AuditControlRecord,
    AuditEventRecord,
    AuditJobRecord,
    AuditPRRecord,
    AuditReservationRecord,
    AuditRunRecord,
    RepositoryRecord,
)

TERMINAL = {"completed", "partial", "blocked", "rejected", "stopped", "pr_ready"}
REMOTE_ACTIVE = {
    "creating_session",
    "planning",
    "implementing",
    "approving",
    "revising",
    "correcting",
}


def now() -> datetime:
    """Return an aware UTC timestamp for durable records."""
    return datetime.now(UTC)


async def control_lock(session: AsyncSession) -> AuditControlRecord:
    """Serialize admission, quota and mutations across all API/worker processes."""
    control = await session.scalar(
        select(AuditControlRecord).where(AuditControlRecord.id == 1).with_for_update()
    )
    if control is None:
        raise HTTPException(503, "Audit database migration required")
    return control


def event(
    session: AsyncSession,
    run: AuditRunRecord,
    message: str,
    kind: str = "stage",
    data: dict | None = None,
    provider_key: str | None = None,
) -> None:
    """Append durable evidence in the same transaction as the state transition."""
    session.add(
        AuditEventRecord(
            batch_id=run.batch_id,
            run_id=run.id,
            kind=kind,
            data=data or {"message": message, "stage": run.stage},
            created_at=now(),
            provider_key=provider_key,
        )
    )


async def create_batch(
    session: AsyncSession,
    repositories: list[UUID],
    key: str,
    deep_review: bool = False,
    force: bool = False,
) -> AuditBatchRecord:
    """Atomically persist one run per selected repository and replay duplicate requests."""
    control = await control_lock(session)
    ids = sorted(set(repositories), key=str)
    fingerprint = digest([list(map(str, ids)), deep_review, force])
    existing = await session.scalar(
        select(AuditBatchRecord).where(AuditBatchRecord.idempotency_key == key)
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(
                409, "Idempotency key already used for different repositories/options"
            )
        return existing
    if not ids:
        raise HTTPException(422, "Select at least one repository")
    records = (
        await session.scalars(select(RepositoryRecord).where(RepositoryRecord.id.in_(ids)))
    ).all()
    if len(records) != len(ids):
        raise HTTPException(404, "Selected repository not found")
    # New clicks with new keys also cannot duplicate a repository's unfinished repair.
    active = await session.scalar(
        select(AuditRunRecord.id).where(
            AuditRunRecord.repository_id.in_(ids), AuditRunRecord.stage.not_in(TERMINAL)
        )
    )
    if active:
        raise HTTPException(409, "A selected repository already has an unfinished audit")
    batch = AuditBatchRecord(
        idempotency_key=key,
        request_hash=fingerprint,
        created_at=now(),
        deep_review=deep_review,
        force=force,
    )
    session.add(batch)
    await session.flush()
    for repository in records:
        run = AuditRunRecord(batch_id=batch.id, repository_id=repository.id, created_at=now())
        session.add(run)
        await session.flush()
        session.add(AuditJobRecord(run_id=run.id, available_at=now()))
        event(session, run, f"Queued {repository.owner}/{repository.name}")
    control.selected = list(map(str, ids))
    await session.commit()
    return batch


async def decide(
    session: AsyncSession, run_id: UUID, version: str, decision: str, feedback: str, key: str
) -> AuditRunRecord:
    """Record approval/rejection/revision only for the currently displayed plan."""
    control = await control_lock(session)
    previous = await session.scalar(
        select(AuditApprovalRecord).where(AuditApprovalRecord.idempotency_key == key)
    )
    run = await session.get(AuditRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Repository run not found")
    if previous:
        if (previous.run_id, previous.version, previous.decision, previous.feedback) != (
            run_id,
            version,
            decision,
            feedback,
        ):
            raise HTTPException(409, "Idempotency key already used for a different decision")
        return run
    batch = await session.get(AuditBatchRecord, run.batch_id)
    if batch.stopped or control.paused:
        raise HTTPException(409, "Run stopped or queue paused")
    if run.stage != "awaiting_approval" or run.plan_version != version:
        raise HTTPException(409, "Plan was superseded or is no longer awaiting approval")
    session.add(
        AuditApprovalRecord(
            run_id=run.id,
            version=version,
            decision=decision,
            feedback=feedback,
            idempotency_key=key,
            created_at=now(),
        )
    )
    run.approved_version = version if decision == "approve" else None
    run.stage = {"approve": "approved", "reject": "rejected", "revise": "revision_queued"}[decision]
    if decision == "revise":
        run.message = feedback
    if decision == "reject":
        run.completed_at = now()
        run.message = "Plan rejected; no implementation or publication authorized"
    job = await session.scalar(select(AuditJobRecord).where(AuditJobRecord.run_id == run.id))
    job.available_at = now()
    event(
        session,
        run,
        f"Owner decision: {decision}",
        "approval",
        {"version": version, "decision": decision},
    )
    await session.commit()
    return run


async def quota(session: AsyncSession, settings: Settings) -> dict:
    """Report app usage including unresolved requests; never claim account-wide certainty."""
    window = now() - timedelta(hours=24)
    reservations = (
        await session.scalars(
            select(AuditReservationRecord).where(
                or_(
                    AuditReservationRecord.created_at > window,
                    AuditReservationRecord.status == "uncertain",
                ),
                AuditReservationRecord.status != "released",
            )
        )
    ).all()
    counted = [r for r in reservations if r.status == "created"]
    uncertain = len(reservations) - len(counted)
    next_at = min((r.created_at + timedelta(hours=24) for r in counted), default=None)
    queued = await session.scalar(
        select(func.count()).select_from(AuditRunRecord).where(AuditRunRecord.stage == "quota_wait")
    )
    control = await session.get(AuditControlRecord, 1)
    return {
        "limit": settings.audit_daily_sessions,
        "used": len(counted),
        "reserved": uncertain,
        "remaining": max(0, settings.audit_daily_sessions - len(reservations)),
        "queued": queued,
        "next_available_at": next_at,
        "provider_retry_at": control.provider_retry_at if control else None,
        "account_remaining_estimate": None,
        "account_note": "Other account activity is not guaranteed by the app budget",
    }


async def snapshot(session: AsyncSession, batch_id: UUID) -> dict:
    """Restore an entire run from the database after refresh or API restart."""
    batch = await session.get(AuditBatchRecord, batch_id)
    if not batch:
        raise HTTPException(404, "Audit run not found")
    rows = (
        await session.scalars(
            select(AuditRunRecord)
            .where(AuditRunRecord.batch_id == batch_id)
            .order_by(AuditRunRecord.created_at)
        )
    ).all()
    runs = []
    for run in rows:
        repo = await session.get(RepositoryRecord, run.repository_id)
        pr = await session.get(AuditPRRecord, run.repository_id)
        runs.append(
            {
                "id": run.id,
                "repository_id": run.repository_id,
                "repository": f"{repo.owner}/{repo.name}",
                "stage": run.stage,
                "base_sha": run.base_sha,
                "checks": run.checks,
                "findings": run.findings,
                "validation": run.validation,
                "plan": run.plan,
                "plan_version": run.plan_version,
                "approved_version": run.approved_version,
                "session_name": run.session_name,
                "session_purpose": "Deep review"
                if batch.deep_review
                else "Repair evidenced failures",
                "remote_state": run.remote_state,
                "corrections": run.corrections,
                "message": run.message,
                "created_at": run.created_at,
                "completed_at": run.completed_at,
                "pr_url": pr.url if pr and run.stage == "pr_ready" else None,
            }
        )
    complete = sum(r.stage in TERMINAL for r in rows)
    return {
        "id": batch.id,
        "created_at": batch.created_at,
        "stopped": batch.stopped,
        "deep_review": batch.deep_review,
        "force": batch.force,
        "status": "stopped"
        if batch.stopped
        else ("completed" if complete == len(rows) else "running"),
        "summary": {
            "completed": complete,
            "total": len(rows),
            "awaiting_approval": sum(r.stage == "awaiting_approval" for r in rows),
            "blocked": sum(r.stage == "blocked" for r in rows),
            "pr_ready": sum(r.stage == "pr_ready" for r in rows),
        },
        "repositories": runs,
    }
