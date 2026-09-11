"""One Jules session adapter for all audit areas.

Session history is intentionally process-local for now. It records requests made
through this API and never invents remote activity or pull requests.
"""

import os
import re
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import structlog

from .config import Settings, get_settings
from .domain import CreateJulesSessionRequest, JulesAuditSession, JulesSessionStatus
from .jules_prompts import build_jules_prompt, get_jules_audit_definition

logger = structlog.get_logger(__name__)

JULES_API_BASE_URL = "https://jules.googleapis.com/v1alpha"
_JULES_SESSION_NAME = re.compile(r"sessions/[A-Za-z0-9_-]+$")


class JulesAuditService:
    """Creates preview or live Jules sessions through a single audited interface."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
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

        api_key = self._api_key()
        if not api_key:
            session = JulesAuditSession(
                session_id=f"unavailable-{uuid4().hex[:8]}",
                audit_area=request.audit_area,
                title=definition.title,
                status=JulesSessionStatus.UNAVAILABLE,
                created_at=now,
                focus=request.focus,
                plan_status="Jules is not configured on this API instance.",
                activity=["Set JULES_API_KEY before requesting a live review."],
                prompt=prompt,
            )
            self._store(session)
            return session

        payload = {
            "prompt": prompt,
            "sourceContext": {
                "source": f"sources/github/{self.settings.jules_source_repository}",
                "githubRepoContext": {"startingBranch": self.settings.jules_starting_branch},
            },
            "automationMode": "AUTO_CREATE_PR",
            "requirePlanApproval": True,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
                response = await client.post(
                    f"{JULES_API_BASE_URL}/sessions",
                    headers={
                        "X-Goog-Api-Key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code not in (200, 201):
                session = self._failed_session(
                    request, definition.title, prompt, now,
                    f"Jules rejected the session request (HTTP {response.status_code}).",
                )
            else:
                data = response.json()
                name = data.get("name") if isinstance(data, dict) else None
                if not isinstance(name, str) or not _JULES_SESSION_NAME.fullmatch(name):
                    session = self._failed_session(
                        request, definition.title, prompt, now,
                        "Jules returned no valid session name.",
                    )
                else:
                    session = JulesAuditSession(
                        session_id=name,
                        audit_area=request.audit_area,
                        title=definition.title,
                        status=JulesSessionStatus.QUEUED,
                        created_at=now,
                        focus=request.focus,
                        plan_status="Jules session created; waiting for plan approval.",
                        activity=["Live review request accepted by Jules.", "Plan approval is required before changes."],
                        prompt=prompt,
                        url=f"https://jules.google.com/session/{name.split('/', maxsplit=1)[1]}",
                    )
        except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("jules_session_request_failed", error_type=type(exc).__name__)
            session = self._failed_session(
                request, definition.title, prompt, now, "Jules service invocation failed."
            )

        self._store(session)
        return session

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
