from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import (
    RepositoryRecord,
    RepositoryScanRecord,
    build_engine,
    build_session_factory,
    create_schema,
)
from .domain import (
    ConnectRepositoryRequest,
    DiscoveredRepository,
    GitHubAccount,
    RepositorySummary,
    ScanSnapshot,
)
from .github import GitHubError, HttpGitHubReader
from .service import RepositoryService, repository_summary

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = build_engine(settings)
    await create_schema(engine)
    client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
    app.state.session_factory = build_session_factory(engine)
    app.state.repository_service = RepositoryService(HttpGitHubReader(settings, client))
    try:
        yield
    finally:
        await client.aclose()
        await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def service(request: Request) -> RepositoryService:
    return request.app.state.repository_service


SessionDependency = Annotated[AsyncSession, Depends(database_session)]
ServiceDependency = Annotated[RepositoryService, Depends(service)]


@app.exception_handler(GitHubError)
async def github_error_handler(_: Request, exc: GitHubError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc), "source": "github"})


@app.get("/healthz", tags=["system"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "oss-maintainer-api"}


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


@app.get(
    "/api/v1/repositories",
    response_model=list[RepositorySummary],
    tags=["repositories"],
)
async def list_repositories(
    session: SessionDependency,
) -> list[RepositorySummary]:
    records = (
        await session.scalars(
            select(RepositoryRecord).order_by(RepositoryRecord.last_scanned_at.desc().nullslast())
        )
    ).all()
    return [repository_summary(record) for record in records]


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
async def get_repository(
    repository_id: UUID, session: SessionDependency
) -> RepositorySummary:
    return repository_summary(await find_repository(session, repository_id))


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
async def scan_history(
    repository_id: UUID, session: SessionDependency
) -> list[ScanSnapshot]:
    await find_repository(session, repository_id)
    records = (
        await session.scalars(
            select(RepositoryScanRecord)
            .where(RepositoryScanRecord.repository_id == repository_id)
            .order_by(RepositoryScanRecord.started_at.desc())
            .limit(50)
        )
    ).all()
    return [
        ScanSnapshot(
            id=item.id,
            repository_id=item.repository_id,
            started_at=item.started_at,
            completed_at=item.completed_at,
            base_sha=item.base_sha,
            signals=item.signals,
            report=item.report,
        )
        for item in records
    ]
