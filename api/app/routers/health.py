from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response

from app import __version__, db
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


def _liveness() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "env": settings.env}


@router.get("/health", summary="Liveness (no dependencies)")
async def health() -> dict[str, Any]:
    return _liveness()


@router.get("/api/health", summary="Liveness, public alias")
async def api_health() -> dict[str, Any]:
    return _liveness()


@router.get("/ready", summary="Readiness (checks the database)")
async def ready(response: Response) -> dict[str, Any]:
    ok, latency_ms = await db.ping()
    if not ok:
        response.status_code = 503
    logger.debug("db.ping", extra={"db_ok": ok, "db_latency_ms": latency_ms})
    return {"status": "ready" if ok else "degraded", "db": {"ok": ok, "latency_ms": latency_ms}}
