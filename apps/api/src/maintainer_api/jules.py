"""One Jules session adapter for all audit areas.

Previews are process-local. Live requests delegate to durable audit runs and the
central quota service; this compatibility adapter never creates provider sessions.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from .config import Settings, get_settings
from .domain import CreateJulesSessionRequest, JulesAuditSession, JulesSessionStatus
from .jules_prompts import build_jules_prompt, get_jules_audit_definition

logger = structlog.get_logger(__name__)

JULES_API_BASE_URL = "https://jules.googleapis.com/v1alpha"


class JulesAuditService:
    """Creates preview or live Jules sessions through a single audited interface."""

    def __init__(self, settings: Settings | None = None, factory=None) -> None:
        self.settings = settings or get_settings()
        self.factory = factory
        self._sessions: dict[str, JulesAuditSession] = {}

    def list_sessions(self) -> list[JulesAuditSession]:
        return sorted(self._sessions.values(), key=lambda session: session.created_at, reverse=True)

    def review_targets(self, audit_area: str) -> list[str]:
        return list(get_jules_audit_definition(audit_area).review_targets)

    async def create_session(self, request: CreateJulesSessionRequest) -> JulesAuditSession:
        definition = get_jules_audit_definition(request.audit_area)
        prompt = build_jules_prompt(request.audit_area, request.focus)
        now = datetime.now(UTC)

        if request.dry_run:
            session = JulesAuditSession(
                session_id=f"preview-{uuid4().hex[:8]}",
                audit_area=request.audit_area,
                title=definition.title,
                status=JulesSessionStatus.PREVIEW,
                created_at=now,
                focus=request.focus,
                plan_status="Preview prepared. Jules was not called.",
                activity=[
                    "Prepared the shared audit prompt.",
                    "Listed the scoped review targets.",
                    "Live execution requires an explicit API request with dry_run set to false.",
                ],
                prompt=prompt,
            )
            self._store(session)
            return session

        if not self._api_key():
            result = JulesAuditSession(
                session_id=f"unavailable-{uuid4().hex[:8]}", audit_area=request.audit_area,
                title=definition.title, status=JulesSessionStatus.UNAVAILABLE, created_at=now,
                focus=request.focus, plan_status="Jules is not configured on this API instance.",
                activity=["Set JULES_API_KEY to enable repair planning."], prompt=prompt,
            )
            self._store(result)
            return result
        if self.factory is None:
            return self._failed_session(
                request,
                definition.title,
                prompt,
                now,
                "Use the authenticated audit backend for live requests",
            )
        from fastapi import HTTPException
        from sqlalchemy import select

        from .audit_service import create_batch
        from .database import AuditControlRecord, RepositoryRecord

        async with self.factory() as database:
            control = await database.get(AuditControlRecord, 1)
            selected = control.selected if control else []
            records = (await database.scalars(select(RepositoryRecord))).all()
            target = [r for r in records if str(r.id) in selected]
            if len(target) != 1:
                raise HTTPException(
                    409, "Select one repository in Audits, or create a multi-repository audit there"
                )
            if not request.idempotency_key:
                raise HTTPException(422, "Live launch requires idempotency_key")
            batch = await create_batch(
                database, [target[0].id], request.idempotency_key, deep_review=True
            )
        result = JulesAuditSession(
            session_id=f"audit-{batch.id}",
            audit_area=request.audit_area,
            title=definition.title,
            status=JulesSessionStatus.QUEUED,
            created_at=now,
            focus=request.focus,
            plan_status="Queued through the durable audit service; quota and plan approval apply.",
            activity=["Audit queued; deterministic checks precede any Jules session."],
            prompt=prompt,
            url=f"{self.settings.public_web_url}/audits/runs/{batch.id}",
        )
        self._store(result)
        return result

    def _failed_session(
        self,
        request: CreateJulesSessionRequest,
        title: str,
        prompt: str,
        created_at: datetime,
        message: str,
    ) -> JulesAuditSession:
        return JulesAuditSession(
            session_id=f"failed-{uuid4().hex[:8]}",
            audit_area=request.audit_area,
            title=title,
            status=JulesSessionStatus.FAILED,
            created_at=created_at,
            focus=request.focus,
            plan_status=message,
            activity=[message],
            prompt=prompt,
        )

    def _store(self, session: JulesAuditSession) -> None:
        self._sessions[session.session_id] = session

    def _api_key(self) -> str:
        if self.settings.jules_api_key is not None:
            return self.settings.jules_api_key.get_secret_value()
        return os.environ.get("JULES_API_KEY", "").strip()
