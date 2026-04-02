"""Tests for DB connection layer and /health endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from polara.api.main import _mask_db_url, create_app
from polara.db.connection import ping_db

# ---------------------------------------------------------------------------
# ping_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_db_returns_true_when_db_reachable() -> None:
    """ping_db() returns True when the DB responds normally."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=None)
    with patch("polara.db.connection.AsyncSessionLocal") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await ping_db()
    assert result is True


@pytest.mark.asyncio
async def test_ping_db_returns_false_on_engine_error() -> None:
    """ping_db() returns False and never raises on DB failure."""
    with patch("polara.db.connection.AsyncSessionLocal") as mock_factory:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("connection refused")
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ping_db()

    assert result is False


# ---------------------------------------------------------------------------
# _mask_db_url
# ---------------------------------------------------------------------------


def test_mask_db_url_leaves_sqlite_unchanged() -> None:
    url = "sqlite+aiosqlite:///./data/polara.db"
    assert _mask_db_url(url) == url


def test_mask_db_url_masks_postgres_credentials() -> None:
    url = "postgresql+asyncpg://user:s3cr3t@localhost:5432/polara"
    masked = _mask_db_url(url)
    assert "s3cr3t" not in masked
    assert "user" not in masked
    assert masked == "postgresql+asyncpg://***@localhost:5432/polara"


def test_mask_db_url_no_credentials_returns_unchanged() -> None:
    url = "postgresql+asyncpg://localhost:5432/polara"
    assert _mask_db_url(url) == url


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app() -> FastAPI:
    return create_app()


@pytest.mark.asyncio
async def test_health_returns_200_when_db_ok(test_app: FastAPI) -> None:
    with patch("polara.api.routes.health.ping_db", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "version" in body
    assert "timestamp" in body


@pytest.mark.asyncio
async def test_health_returns_503_when_db_down(test_app: FastAPI) -> None:
    with patch("polara.api.routes.health.ping_db", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = False
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"


@pytest.mark.asyncio
async def test_health_timestamp_is_utc_iso8601(test_app: FastAPI) -> None:
    with patch("polara.api.routes.health.ping_db", new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = True
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    ts = response.json()["timestamp"]
    # UTC ISO 8601 timestamps end with +00:00 or Z
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"Not UTC ISO 8601: {ts!r}"
