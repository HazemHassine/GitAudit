"""Opt-in PostgreSQL concurrency proof against an isolated migrated database."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_audits import FakeGitHub, FakeJules, FakeWorkspace, queued, repository, source_files

from maintainer_api.audit_service import create_batch, quota
from maintainer_api.audit_worker import AuditWorker
from maintainer_api.config import Settings
from maintainer_api.database import AuditBatchRecord, AuditRunRecord

pytestmark = pytest.mark.skipif(not os.environ.get("AUDIT_TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL verification database")


async def test_postgres_concurrent_admission_and_session_budget():
    engine = create_async_engine(os.environ["AUDIT_TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        repo = await repository(factory, "concurrent")
        key = str(uuid4())
        async def create():
            async with factory() as session:
                return (await create_batch(session, [repo.id], key)).id
        results = await asyncio.wait_for(asyncio.gather(create(), create()), 10)
        assert results[0] == results[1]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(AuditBatchRecord)) == 1
            first = await session.scalar(select(AuditRunRecord))
            first.stage = "repair_queued"
            first.branch = "main"
            first.base_sha = "a" * 40
            first.findings = [{"key": "test", "area": "tests", "priority": 2}]
            await session.commit()
        second_repo = await repository(factory, "quota-second")
        second = await queued(factory, second_repo)
        async with factory() as session:
            current = await session.get(AuditRunRecord, second.id)
            current.stage, current.branch, current.base_sha = "repair_queued", "main", "a" * 40
            await session.commit()
        settings = Settings(_env_file=None, audit_daily_sessions=1)
        jules = FakeJules()
        worker = AuditWorker(factory, settings, FakeGitHub(source_files()), jules, FakeWorkspace)
        first_claim, second_claim = await asyncio.gather(worker.claim(), worker.claim())
        assert first_claim[0] != second_claim[0]
        await asyncio.wait_for(asyncio.gather(
            worker.create_session(*first_claim, "owner/concurrent"),
            worker.create_session(*second_claim, "owner/quota-second"),
        ), 10)
        assert jules.creations == 1
        async with factory() as session:
            assert (await quota(session, settings))["remaining"] == 0
    finally:
        await engine.dispose()
