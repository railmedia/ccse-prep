"""Liveness is dependency-free, so it is safe to assert in unit tests."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health_is_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_sets_request_id_header() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers={"x-request-id": "abc123"})

    assert response.headers["x-request-id"] == "abc123"
