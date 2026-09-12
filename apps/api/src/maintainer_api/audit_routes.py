"""Versioned durable audit API and replayable event stream."""

import asyncio
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit_service import TERMINAL, control_lock, create_batch, decide, event, now, quota, snapshot
from .config import get_settings
from .database import (
    AuditBatchRecord,
    AuditControlRecord,
    AuditEventRecord,
    AuditRunRecord,
)

router = APIRouter(prefix="/api/v1/audits", tags=["audits"])


async def session_dependency(request: Request):
    """Each request gets its own session; streaming opens separate short sessions."""
    async with request.app.state.session_factory() as session:
        yield session


Session = Annotated[AsyncSession, Depends(session_dependency)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


class CreateAuditRequest(BaseModel):
    """Explicit repository selection and optional review/recheck choices."""

    repository_ids: list[UUID] = Field(min_length=1, max_length=100)
    deep_review: bool = False
    force: bool = False


class PlanDecisionRequest(BaseModel):
    """A decision about one actual plan version, never a blanket approval."""

    version: str = Field(min_length=64, max_length=64)
    decision: Literal["approve", "reject", "revise"]
    feedback: str = Field(default="", max_length=10000)


class SelectionRequest(BaseModel):
    """Persist the owner's repository selection across browsers."""

    repository_ids: list[UUID] = Field(max_length=100)


class RepositoryAuditResult(BaseModel):
    """Recorded repository result exposed to the dashboard."""

    id: UUID
    repository_id: UUID
    repository: str
    stage: str
    base_sha: str | None
    checks: list[dict]
    findings: list[dict]
    validation: list[dict]
    plan: dict | None
    plan_version: str | None
    approved_version: str | None
    session_name: str | None
    session_purpose: str
    remote_state: str | None
    corrections: int
    message: str | None
    created_at: str
    completed_at: str | None
    pr_url: str | None


class AuditSnapshot(BaseModel):
    """Stable run link and task-count progress; no synthetic percentage."""

    id: UUID
    created_at: str
    stopped: bool
    deep_review: bool
    force: bool
    status: str
    summary: dict[str, int]
    repositories: list[RepositoryAuditResult]


@router.get("/settings")
async def audit_settings(session: Session) -> dict:
    """Read saved repository choices."""
    control = await session.get(AuditControlRecord, 1)
    return {"repository_ids": control.selected if control else []}


@router.put("/settings")
async def save_settings(payload: SelectionRequest, session: Session) -> dict:
    """Persist selected repositories under the owner lock."""
    control = await control_lock(session)
    control.selected = list(map(str, payload.repository_ids))
    await session.commit()
    return {"repository_ids": control.selected}


@router.get("/status")
async def audit_status(session: Session) -> dict:
    """Show worker heartbeat, pause state and centrally enforced quota."""
    control = await session.get(AuditControlRecord, 1)
    heartbeat = control.heartbeat if control else None
    online = (
        heartbeat is not None
        and (now().replace(tzinfo=None) - heartbeat.replace(tzinfo=None)).total_seconds() < 45
    )
    return {
        "paused": control.paused if control else False,
        "worker_online": online,
        "heartbeat": heartbeat,
        "local_slots": 2,
        "jules_slots": get_settings().audit_jules_slots,
        "quota": await quota(session, get_settings()),
    }


@router.post("/queue/{action}")
async def queue_control(action: Literal["pause", "resume"], session: Session) -> dict:
    """Pause new local actions while allowing remote read-only reconciliation."""
    control = await control_lock(session)
    control.paused = action == "pause"
    await session.commit()
    return {"paused": control.paused}


@router.post("/runs", response_model=AuditSnapshot, status_code=202)
async def start_run(payload: CreateAuditRequest, session: Session, key: Key) -> dict:
    """Create or replay a durable batch request."""
    batch = await create_batch(
        session, payload.repository_ids, key, payload.deep_review, payload.force
    )
    return jsonable_encoder(await snapshot(session, batch.id))


@router.get("/runs", response_model=list[AuditSnapshot])
async def list_runs(session: Session) -> list[dict]:
    """List recent durable runs with their actual recorded outcomes."""
    batches = (
        await session.scalars(
            select(AuditBatchRecord).order_by(AuditBatchRecord.created_at.desc()).limit(50)
        )
    ).all()
    return [jsonable_encoder(await snapshot(session, batch.id)) for batch in batches]


@router.get("/runs/{batch_id}", response_model=AuditSnapshot)
async def get_run(batch_id: UUID, session: Session) -> dict:
    """Restore a permanent run URL."""
    return jsonable_encoder(await snapshot(session, batch_id))


@router.post("/runs/{batch_id}/stop", response_model=AuditSnapshot)
async def stop_run(batch_id: UUID, session: Session) -> dict:
    """Prevent all further local mutations; continue observing already-running Jules work."""
    await control_lock(session)
    batch = await session.get(AuditBatchRecord, batch_id)
    if not batch:
        raise HTTPException(404, "Audit run not found")
    batch.stopped = True
    runs = (
        await session.scalars(select(AuditRunRecord).where(AuditRunRecord.batch_id == batch_id))
    ).all()
    for run in runs:
        if run.stage not in TERMINAL:
            run.stage = "stopped"
            run.approved_version = None
            run.completed_at = now()
            run.message = (
                "Stopped locally. The supported Jules API does not guarantee cancellation; remote work remains tracked."
                if run.session_name
                else "Stopped before further execution or publication"
            )
            event(session, run, run.message)
    await session.commit()
    return jsonable_encoder(await snapshot(session, batch_id))


@router.post("/repositories/{run_id}/decision", response_model=AuditSnapshot)
async def plan_decision(
    run_id: UUID, payload: PlanDecisionRequest, session: Session, key: Key
) -> dict:
    """Approve, reject or request revision of exactly the supplied plan version."""
    if payload.decision == "revise" and not payload.feedback.strip():
        raise HTTPException(422, "Describe the requested revision")
    run = await decide(session, run_id, payload.version, payload.decision, payload.feedback, key)
    return jsonable_encoder(await snapshot(session, run.batch_id))


@router.post("/repositories/{run_id}/retry", response_model=AuditSnapshot, status_code=202)
async def retry_run(run_id: UUID, session: Session, key: Key) -> dict:
    """An explicit retry starts a new batch and may consume a new reserved session."""
    run = await session.get(AuditRunRecord, run_id)
    if not run or run.stage not in TERMINAL:
        raise HTTPException(409, "Only a finished or blocked repository can be retried")
    if run.operation or (run.session_name and run.remote_state not in ("COMPLETED", "FAILED")):
        raise HTTPException(409, "Reconcile existing remote work before opening another session")
    batch = await create_batch(session, [run.repository_id], key, force=True)
    return jsonable_encoder(await snapshot(session, batch.id))


@router.get("/runs/{batch_id}/events")
async def list_events(batch_id: UUID, session: Session, after: int = 0) -> list[dict]:
    """Polling fallback uses the same durable cursor as SSE."""
    await snapshot(session, batch_id)
    rows = (
        await session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.batch_id == batch_id, AuditEventRecord.id > after)
            .order_by(AuditEventRecord.id)
            .limit(500)
        )
    ).all()
    return [
        {"id": e.id, "run_id": e.run_id, "kind": e.kind, "created_at": e.created_at, "data": e.data}
        for e in rows
    ]


@router.get("/runs/{batch_id}/stream")
async def stream_events(
    batch_id: UUID,
    request: Request,
    session: Session,
    last_event_id: Annotated[str | None, Header()] = None,
    after: int = 0,
):
    """Stream committed events with Last-Event-ID replay and heartbeat comments."""
    await snapshot(session, batch_id)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(422, "Invalid event cursor") from exc
    factory = request.app.state.session_factory

    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            async with factory() as owned_session:
                rows = await list_events(batch_id, owned_session, cursor)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: audit\ndata: {json.dumps(jsonable_encoder(row))}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
