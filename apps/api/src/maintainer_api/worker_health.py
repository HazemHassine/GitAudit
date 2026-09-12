"""Compose health probe based on the durable worker heartbeat."""

import asyncio

from .audit_service import now
from .config import get_settings
from .database import AuditControlRecord, build_engine, build_session_factory


async def main() -> None:
    """Fail if no worker has renewed its heartbeat in the last 45 seconds."""
    engine = build_engine(get_settings())
    try:
        async with build_session_factory(engine)() as session:
            control = await session.get(AuditControlRecord, 1)
            if (
                not control
                or not control.heartbeat
                or (
                    now().replace(tzinfo=None) - control.heartbeat.replace(tzinfo=None)
                ).total_seconds()
                > 45
            ):
                raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
