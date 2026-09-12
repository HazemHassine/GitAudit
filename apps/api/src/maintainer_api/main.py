from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import bind_contextvars, clear_contextvars

from .activity import ActivityService
from .audit_auth import authenticated
from .audit_auth import router as auth_router
from .audit_routes import router as audit_router
from .ci_audit import CiAuditService
from .config import get_settings
from .coordinator import RepositorySyncCoordinator
from .coverage import CoverageService
from .curation import (
    PROMPT_VERSION,
    AssessmentInProgressError,
    CurationConfigurationError,
    CurationError,
    CurationService,
    assessment_snapshot,
    build_curation_agent,
)
from .database import (
    RepositoryAssessmentRecord,
    RepositoryRecord,
    RepositoryScanRecord,
    build_engine,
    build_session_factory,
)
from .domain import (
    AISettingsStatus,
    CiAuditSummary,
    ConnectRepositoryRequest,
    CoverageSummary,
    CreateJulesSessionRequest,
    CreateReproductionRequest,
    CurationAssessment,
    DashboardActivity,
    DashboardStats,
    DiscoveredRepository,
    GenerateTestsRequest,
    GitHubAccount,
    GitHubSettingsStatus,
    JulesAuditSession,
    JulesCiSession,
    JulesTestSession,
    MonitoringState,
    RepositorySummary,
    ReproductionRun,
    ScanSnapshot,
    SyncStatus,
    TriggerCiAnalysisRequest,
)
from .github import GitHubConfigurationError, GitHubError, HttpGitHubReader
from .jules import JulesAuditService
from .observability import HTTP_DURATION, HTTP_REQUESTS, configure_logging
from .reproduction import ReproductionService
from .service import (
    RepositoryService,
    ScanInProgressError,
    repository_summary,
    scan_snapshot,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = build_engine(settings)
    client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
    session_factory = build_session_factory(engine)
    github_reader = HttpGitHubReader(settings, client)
    repository_service = RepositoryService(github_reader, settings.scan_stale_after_minutes)
    activity_service = ActivityService(github_reader, settings.scan_stale_after_minutes)
    curation_agent = build_curation_agent(settings) if settings.openai_configured else None
    curation_service = CurationService(github_reader, settings.openai_model, curation_agent)
    reproduction_service = ReproductionService(github_reader)
    jules_service = JulesAuditService(settings, session_factory)
    coverage_service = CoverageService(settings, jules_service)
    ci_audit_service = CiAuditService(jules_service)
    async with session_factory() as recovery_session:
        recovered = await repository_service.recover_interrupted_scans(recovery_session)
        if recovered:
            logger.warning("interrupted_scans_recovered", count=recovered)
        recovered_assessments = await curation_service.recover_interrupted_assessments(
            recovery_session
        )
        if recovered_assessments:
            logger.warning(
                "interrupted_assessments_recovered", count=recovered_assessments
            )
    coordinator = RepositorySyncCoordinator(settings, session_factory, repository_service)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.repository_service = repository_service
    app.state.activity_service = activity_service
    app.state.curation_service = curation_service
    app.state.reproduction_service = reproduction_service
    app.state.coverage_service = coverage_service
    app.state.ci_audit_service = ci_audit_service
    app.state.jules_service = jules_service
    app.state.sync_coordinator = coordinator
    coordinator.start()
    try:
        yield
    finally:
        await coordinator.close()
        await client.aclose()
        await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(audit_router)


@app.middleware("http")
async def owner_access(request: Request, call_next):
    """Protect every mutation and audit evidence endpoint with owner authentication."""
    mutation = request.method not in ("GET", "HEAD", "OPTIONS")
    login = request.url.path == "/api/v1/auth/login"
    if mutation:
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
    protected_read = request.url.path.startswith("/api/v1/audits")
    if (mutation and not login or protected_read) and request.method != "OPTIONS" and not authenticated(request):
        return JSONResponse(status_code=401, content={"detail": "Owner login required"})
    return await call_next(request)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    clear_contextvars()
    bind_contextvars(request_id=request_id)
    started = monotonic()
    response_status = 500
    try:
        response = await call_next(request)
        response_status = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        duration = monotonic() - started
        HTTP_REQUESTS.labels(method=request.method, path=path, status=str(response_status)).inc()
        HTTP_DURATION.labels(method=request.method, path=path).observe(duration)
        logger.info(
            "http_request",
            method=request.method,
            path=path,
            status=response_status,
            duration_ms=round(duration * 1000, 2),
        )
        clear_contextvars()


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def service(request: Request) -> RepositoryService:
    return request.app.state.repository_service


def sync_coordinator(request: Request) -> RepositorySyncCoordinator:
    return request.app.state.sync_coordinator


def curation(request: Request) -> CurationService:
    return request.app.state.curation_service


def activity(request: Request) -> ActivityService:
    return request.app.state.activity_service


SessionDependency = Annotated[AsyncSession, Depends(database_session)]
ServiceDependency = Annotated[RepositoryService, Depends(service)]
CoordinatorDependency = Annotated[RepositorySyncCoordinator, Depends(sync_coordinator)]
CurationDependency = Annotated[CurationService, Depends(curation)]
ActivityDependency = Annotated[ActivityService, Depends(activity)]


@app.exception_handler(GitHubError)
async def github_error_handler(_: Request, exc: GitHubError) -> JSONResponse:
    status_code = 503 if isinstance(exc, GitHubConfigurationError) else 502
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc), "source": "github"},
    )


@app.exception_handler(ScanInProgressError)
async def scan_in_progress_handler(_: Request, exc: ScanInProgressError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(CurationError)
async def curation_error_handler(_: Request, exc: CurationError) -> JSONResponse:
    if isinstance(exc, AssessmentInProgressError):
        status_code = 409
    elif isinstance(exc, CurationConfigurationError):
        status_code = 503
    else:
        status_code = 502
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc), "source": "curation"},
    )


@app.get("/healthz", tags=["system"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "oss-maintainer-api"}


@app.get("/readyz", tags=["system"])
async def readiness(session: SessionDependency) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get(
    "/api/v1/settings/github",
    response_model=GitHubSettingsStatus,
    tags=["settings"],
)
async def github_settings() -> GitHubSettingsStatus:
    return GitHubSettingsStatus(
        configured=settings.github_configured,
        auth_mode=settings.resolved_github_auth_mode,
        app_install_url=settings.github_app_install_url,
        auto_scan_on_startup=settings.auto_scan_on_startup,
        auto_scan_interval_minutes=settings.auto_scan_interval_minutes,
        scan_stale_after_minutes=settings.scan_stale_after_minutes,
    )


@app.get(
    "/api/v1/settings/ai",
    response_model=AISettingsStatus,
    tags=["settings"],
)
async def ai_settings() -> AISettingsStatus:
    return AISettingsStatus(
        configured=settings.openai_configured,
        model=settings.openai_model,
        prompt_version=PROMPT_VERSION,
    )


@app.get("/api/v1/github/account", response_model=GitHubAccount, tags=["github"])
async def github_account(repository_service: ServiceDependency) -> GitHubAccount:
    return await repository_service.account()


@app.get(
    "/api/v1/github/repositories",
    response_model=list[DiscoveredRepository],
    tags=["github"],
)
async def discover_repositories(
    session: SessionDependency,
    repository_service: ServiceDependency,
) -> list[DiscoveredRepository]:
    return await repository_service.discover(session)


@app.get("/api/v1/sync", response_model=SyncStatus, tags=["scans"])
async def sync_status(coordinator: CoordinatorDependency) -> SyncStatus:
    return coordinator.status


@app.post(
    "/api/v1/sync",
    response_model=SyncStatus,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["scans"],
)
async def sync_all_repositories(
    coordinator: CoordinatorDependency, force: bool = False
) -> SyncStatus:
    return coordinator.trigger(force=force)


@app.get(
    "/api/v1/repositories",
    response_model=list[RepositorySummary],
    tags=["repositories"],
)
async def list_repositories(session: SessionDependency) -> list[RepositorySummary]:
    records = (
        await session.scalars(
            select(RepositoryRecord)
            .where(RepositoryRecord.monitoring_state == MonitoringState.ACTIVE.value)
            .order_by(RepositoryRecord.last_scanned_at.desc().nullslast())
        )
    ).all()
    return [repository_summary(record, settings.scan_stale_after_minutes) for record in records]


@app.post(
    "/api/v1/repositories",
    response_model=RepositorySummary,
    status_code=status.HTTP_201_CREATED,
    tags=["repositories"],
)
async def connect_repository(
    request: ConnectRepositoryRequest,
    session: SessionDependency,
    repository_service: ServiceDependency,
) -> RepositorySummary:
    return await repository_service.connect(session, request.owner, request.name)


async def find_repository(session: AsyncSession, repository_id: UUID) -> RepositoryRecord:
    record = await session.get(RepositoryRecord, repository_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return record


@app.get(
    "/api/v1/repositories/{repository_id}",
    response_model=RepositorySummary,
    tags=["repositories"],
)
async def get_repository(repository_id: UUID, session: SessionDependency) -> RepositorySummary:
    return repository_summary(
        await find_repository(session, repository_id), settings.scan_stale_after_minutes
    )


@app.delete(
    "/api/v1/repositories/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["repositories"],
)
async def exclude_repository(
    repository_id: UUID,
    session: SessionDependency,
    repository_service: ServiceDependency,
) -> Response:
    await repository_service.exclude(session, await find_repository(session, repository_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/v1/repositories/{repository_id}/scans",
    response_model=ScanSnapshot,
    status_code=status.HTTP_201_CREATED,
    tags=["scans"],
)
async def scan_repository(
    repository_id: UUID,
    session: SessionDependency,
    repository_service: ServiceDependency,
) -> ScanSnapshot:
    record = await find_repository(session, repository_id)
    return await repository_service.scan(session, record)


@app.get(
    "/api/v1/repositories/{repository_id}/scans",
    response_model=list[ScanSnapshot],
    tags=["scans"],
)
async def scan_history(repository_id: UUID, session: SessionDependency) -> list[ScanSnapshot]:
    await find_repository(session, repository_id)
    records = (
        await session.scalars(
            select(RepositoryScanRecord)
            .where(RepositoryScanRecord.repository_id == repository_id)
            .order_by(RepositoryScanRecord.started_at.desc())
            .limit(50)
        )
    ).all()
    return [scan_snapshot(item) for item in records]


@app.get(
    "/api/v1/repositories/{repository_id}/scans/{scan_id}",
    response_model=ScanSnapshot,
    tags=["scans"],
)
async def get_scan(repository_id: UUID, scan_id: UUID, session: SessionDependency) -> ScanSnapshot:
    record = await session.scalar(
        select(RepositoryScanRecord).where(
            RepositoryScanRecord.id == scan_id,
            RepositoryScanRecord.repository_id == repository_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan_snapshot(record)


@app.post(
    "/api/v1/repositories/{repository_id}/assessments",
    response_model=CurationAssessment,
    status_code=status.HTTP_201_CREATED,
    tags=["curation"],
)
async def assess_repository(
    repository_id: UUID,
    session: SessionDependency,
    curation_service: CurationDependency,
) -> CurationAssessment:
    repository = await find_repository(session, repository_id)
    return await curation_service.assess(session, repository)


@app.get(
    "/api/v1/repositories/{repository_id}/assessments",
    response_model=list[CurationAssessment],
    tags=["curation"],
)
async def assessment_history(
    repository_id: UUID, session: SessionDependency
) -> list[CurationAssessment]:
    await find_repository(session, repository_id)
    records = (
        await session.scalars(
            select(RepositoryAssessmentRecord)
            .where(RepositoryAssessmentRecord.repository_id == repository_id)
            .order_by(RepositoryAssessmentRecord.started_at.desc())
            .limit(20)
        )
    ).all()
    return [assessment_snapshot(item) for item in records]


@app.get("/api/v1/dashboard/stats", response_model=DashboardStats, tags=["dashboard"])
async def dashboard_stats(session: SessionDependency, activity_service: ActivityDependency) -> DashboardStats:
    return await activity_service.dashboard_stats(session)

@app.get("/api/v1/dashboard/activity", response_model=DashboardActivity, tags=["dashboard"])
async def dashboard_activity(
    session: SessionDependency,
    activity_service: ActivityDependency,
    repository_service: ServiceDependency,
) -> DashboardActivity:
    account = await repository_service.account()
    return await activity_service.dashboard_activity(session, account.login)

@app.post("/api/v1/dashboard/refresh", response_model=DashboardActivity, status_code=202, tags=["dashboard"])
async def refresh_dashboard(
    session: SessionDependency,
    activity_service: ActivityDependency,
    repository_service: ServiceDependency,
) -> DashboardActivity:
    account = await repository_service.account()
    return await activity_service.refresh_all(session, account.login)

@app.get("/api/v1/repositories/{repository_id}/activity", tags=["dashboard"])
async def repository_activity(
    repository_id: UUID,
    session: SessionDependency,
    activity_service: ActivityDependency,
) -> dict:
    repository = await find_repository(session, repository_id)
    return await activity_service.repository_activity(session, repository)

def get_reproduction_service(request: Request) -> ReproductionService:
    return request.app.state.reproduction_service

ReproductionDependency = Annotated[ReproductionService, Depends(get_reproduction_service)]


@app.post("/api/v1/repositories/{repository_id}/reproductions", status_code=202, tags=["reproduction"])
async def create_reproduction(
    repository_id: UUID, request_data: CreateReproductionRequest, session: SessionDependency,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=200)],
) -> dict:
    """Queue safe repository checks; historical reproduction records remain readable."""
    from fastapi.encoders import jsonable_encoder

    from .audit_service import create_batch, snapshot
    if request_data.custom_command:
        raise HTTPException(422, "Custom commands are replaced by manifest-driven checks in Audits")
    batch = await create_batch(session, [repository_id], idempotency_key, force=True)
    return jsonable_encoder(await snapshot(session, batch.id))


@app.get(
    "/api/v1/repositories/{repository_id}/reproductions",
    response_model=list[ReproductionRun],
    tags=["reproduction"]
)
async def list_reproductions(
    repository_id: UUID,
    session: SessionDependency,
    service: ReproductionDependency,
) -> list[ReproductionRun]:
    stmt = select(RepositoryRecord).where(RepositoryRecord.id == repository_id)
    result = await session.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Repository not found")
    return await service.list_reproductions(session, repository_id)


@app.get(
    "/api/v1/reproductions/{reproduction_id}",
    response_model=ReproductionRun,
    tags=["reproduction"]
)
async def get_reproduction(
    reproduction_id: UUID,
    session: SessionDependency,
    service: ReproductionDependency,
) -> ReproductionRun:
    try:
        return await service.get_reproduction(session, reproduction_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post(
    "/api/v1/reproductions/{reproduction_id}/cancel",
    response_model=ReproductionRun,
    tags=["reproduction"]
)
async def cancel_reproduction(
    reproduction_id: UUID,
    session: SessionDependency,
    service: ReproductionDependency,
) -> ReproductionRun:
    try:
        return await service.cancel_reproduction(session, reproduction_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/reproductions/{reproduction_id}/stream", tags=["reproduction"])
async def stream_reproduction(
    reproduction_id: UUID,
    session: SessionDependency,
    service: ReproductionDependency,
):
    try:
        # Check if the reproduction exists
        await service.get_reproduction(session, reproduction_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(service.stream_reproduction(reproduction_id), media_type="text/event-stream")


def get_coverage_service(request: Request) -> CoverageService:
    service = getattr(request.app.state, "coverage_service", None)
    if service is None:
        service = CoverageService(settings, get_jules_service(request))
        request.app.state.coverage_service = service
    return service


CoverageDependency = Annotated[CoverageService, Depends(get_coverage_service)]


@app.get(
    "/api/v1/coverage/summary",
    response_model=CoverageSummary,
    tags=["coverage"],
)
async def get_coverage_summary(
    service: CoverageDependency,
) -> CoverageSummary:
    return service.get_coverage_summary()


@app.post(
    "/api/v1/coverage/generate-tests",
    response_model=JulesTestSession,
    tags=["coverage"],
)
async def generate_tests(
    payload: GenerateTestsRequest,
    service: CoverageDependency,
) -> JulesTestSession:
    return await service.trigger_jules_test_generation(payload)


@app.get(
    "/api/v1/coverage/stream",
    tags=["coverage"],
)
async def stream_coverage(
    service: CoverageDependency,
):
    return StreamingResponse(service.stream_events(), media_type="text/event-stream")


@app.get(
    "/api/v1/repositories/{repository_id}/coverage",
    response_model=CoverageSummary,
    tags=["coverage"],
)
async def get_repository_coverage(
    repository_id: UUID,
    session: SessionDependency,
    service: CoverageDependency,
) -> CoverageSummary:
    repository = await find_repository(session, repository_id)
    return service.get_repository_coverage_summary(repository)


def get_ci_audit_service(request: Request) -> CiAuditService:
    service = getattr(request.app.state, "ci_audit_service", None)
    if service is None:
        service = CiAuditService(get_jules_service(request))
        request.app.state.ci_audit_service = service
    return service


CiAuditDependency = Annotated[CiAuditService, Depends(get_ci_audit_service)]


def get_jules_service(request: Request) -> JulesAuditService:
    service = getattr(request.app.state, "jules_service", None)
    if service is None:
        service = JulesAuditService(settings, getattr(request.app.state, "session_factory", None))
        request.app.state.jules_service = service
    return service


JulesDependency = Annotated[JulesAuditService, Depends(get_jules_service)]


@app.get(
    "/api/v1/jules/sessions",
    response_model=list[JulesAuditSession],
    tags=["jules"],
)
async def list_jules_sessions(service: JulesDependency) -> list[JulesAuditSession]:
    """List sessions prepared through this API process, newest first."""
    return service.list_sessions()


@app.post(
    "/api/v1/jules/sessions",
    response_model=JulesAuditSession,
    status_code=status.HTTP_201_CREATED,
    tags=["jules"],
)
async def create_jules_session(
    payload: CreateJulesSessionRequest,
    service: JulesDependency,
) -> JulesAuditSession:
    """Prepare a review by default; a live request must set ``dry_run`` to false."""
    return await service.create_session(payload)


@app.get(
    "/api/v1/repositories/{repository_id}/ci-audit",
    response_model=CiAuditSummary,
    tags=["ci-audit"],
)
async def get_repository_ci_audit(
    repository_id: UUID,
    session: SessionDependency,
    service: CiAuditDependency,
) -> CiAuditSummary:
    repo = await find_repository(session, repository_id)
    return await service.get_ci_audit_for_repository(repo)


@app.get(
    "/api/v1/ci-audit/summary",
    response_model=CiAuditSummary,
    tags=["ci-audit"],
)
@app.post(
    "/api/v1/ci-audit/summary",
    response_model=CiAuditSummary,
    tags=["ci-audit"],
)
async def get_general_ci_audit(
    service: CiAuditDependency,
) -> CiAuditSummary:
    return await service.get_local_ci_audit()


@app.post(
    "/api/v1/ci-audit/lint",
    response_model=CiAuditSummary,
    tags=["ci-audit"],
)
async def trigger_general_ci_lint(
    service: CiAuditDependency,
) -> CiAuditSummary:
    return await service.get_local_ci_audit()


@app.post("/api/v1/ci-audit/jules", response_model=JulesCiSession, tags=["ci-audit"])
async def trigger_general_ci_jules(
    payload: TriggerCiAnalysisRequest,
    service: CiAuditDependency,
) -> JulesCiSession:
    return await service.trigger_jules_analysis(payload)


@app.post(
    "/api/v1/repositories/{repository_id}/ci-audit/lint",
    response_model=CiAuditSummary,
    tags=["ci-audit"],
)
async def trigger_ci_lint(
    repository_id: UUID,
    session: SessionDependency,
    service: CiAuditDependency,
) -> CiAuditSummary:
    repo = await find_repository(session, repository_id)
    return await service.get_ci_audit_for_repository(repo)
