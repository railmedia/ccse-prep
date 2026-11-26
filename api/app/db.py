from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.settings import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session


async def ping() -> tuple[bool, float]:
    """Return (reachable, latency_ms) for the readiness probe."""
    started = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("db.ping_failed", exc_info=True)
        return False, round((time.perf_counter() - started) * 1000, 2)
    return True, round((time.perf_counter() - started) * 1000, 2)


async def dispose() -> None:
    await engine.dispose()
