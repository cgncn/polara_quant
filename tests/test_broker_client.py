"""Tests for IBClient — ib_async IB is fully mocked."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polara.broker.client import _BACKOFF_SEQUENCE, IBClient


def make_mock_ib(connected: bool = False) -> MagicMock:
    """Build a minimal mock IB instance."""
    ib = MagicMock()
    ib.isConnected.return_value = connected
    ib.connectAsync = AsyncMock()
    ib.disconnect = MagicMock()
    # disconnectedEvent supports += operator
    ib.disconnectedEvent = MagicMock()
    return ib


@pytest.fixture
def client_with_mock_ib():
    """IBClient with a mocked IB instance injected."""
    with patch("polara.broker.client.IB") as MockIB:
        mock_ib = make_mock_ib(connected=False)
        MockIB.return_value = mock_ib
        client = IBClient(host="localhost", port=4003, client_id=1)
        yield client, mock_ib


# ── connect ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_calls_connectAsync(client_with_mock_ib):
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = False
    await client.connect()
    mock_ib.connectAsync.assert_called_once_with(
        host="localhost", port=4003, clientId=1, timeout=10
    )


@pytest.mark.asyncio
async def test_connect_logs_warning_on_failure(client_with_mock_ib, caplog):
    import logging
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync.side_effect = ConnectionRefusedError("refused")
    with caplog.at_level(logging.WARNING, logger="polara.broker.client"):
        await client.connect()
    assert any("could not connect" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_connect_no_exception_on_failure(client_with_mock_ib):
    """connect() must not raise even if IB Gateway is unreachable."""
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = False
    mock_ib.connectAsync.side_effect = OSError("unreachable")
    # Must NOT raise
    await client.connect()


@pytest.mark.asyncio
async def test_connect_idempotent_when_already_connected(client_with_mock_ib):
    """connect() returns immediately if already connected."""
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = True
    await client.connect()
    mock_ib.connectAsync.assert_not_called()


# ── disconnect ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_sets_shutdown_flag(client_with_mock_ib):
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = True
    await client.disconnect()
    assert client._shutdown is True


@pytest.mark.asyncio
async def test_disconnect_calls_ib_disconnect_when_connected(client_with_mock_ib):
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = True
    await client.disconnect()
    mock_ib.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_cancels_reconnect_task(client_with_mock_ib):
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = False
    # Simulate an active reconnect task
    async def slow_loop() -> None:
        await asyncio.sleep(9999)
    client._reconnect_task = asyncio.create_task(slow_loop())
    await client.disconnect()
    assert client._reconnect_task.cancelled()


# ── _reconnect_loop ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconnect_loop_exits_when_shutdown(client_with_mock_ib):
    """If _shutdown is set, reconnect loop exits without calling connectAsync."""
    client, mock_ib = client_with_mock_ib
    mock_ib.isConnected.return_value = False
    client._shutdown = True

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        # Immediately check shutdown — since it's set, loop should exit
        if client._shutdown:
            return

    with patch("polara.broker.client.asyncio.sleep", fake_sleep):
        await client._reconnect_loop()

    # connectAsync must not be called when shutdown is set
    mock_ib.connectAsync.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_loop_uses_backoff_sequence(client_with_mock_ib):
    """_reconnect_loop sleeps using the backoff sequence and exits after reconnect."""
    client, mock_ib = client_with_mock_ib
    client._shutdown = False

    sleep_calls: list[float] = []
    connect_calls = 0

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_connect(**kwargs: object) -> None:
        nonlocal connect_calls
        connect_calls += 1
        # Succeed on the second connect attempt
        if connect_calls >= 2:
            mock_ib.isConnected.return_value = True

    mock_ib.connectAsync.side_effect = fake_connect

    with patch("polara.broker.client.asyncio.sleep", fake_sleep):
        await client._reconnect_loop()

    # First sleep should use the first backoff value
    assert sleep_calls[0] == _BACKOFF_SEQUENCE[0]
    assert connect_calls == 2


# ── _on_disconnected ───────────────────────────────────────────────────────────

def test_on_disconnected_does_nothing_when_shutdown(client_with_mock_ib):
    client, _ = client_with_mock_ib
    client._shutdown = True
    client._on_disconnected()
    assert client._reconnect_task is None


def test_on_disconnected_cancels_existing_task(client_with_mock_ib):
    """If a reconnect task is already running, _on_disconnected cancels it."""
    client, _ = client_with_mock_ib
    client._shutdown = False

    # The _on_disconnected should cancel the old task
    # We can't easily run create_task without an event loop here,
    # so just verify the guard path: old task done => no cancel needed
    old_task_mock = MagicMock()
    old_task_mock.done.return_value = False
    old_task_mock.cancel = MagicMock()
    client._reconnect_task = old_task_mock

    with patch("asyncio.create_task", return_value=MagicMock()):
        client._on_disconnected()

    old_task_mock.cancel.assert_called_once()


# ── backoff sequence ───────────────────────────────────────────────────────────

def test_backoff_sequence_values():
    assert _BACKOFF_SEQUENCE == [1, 2, 4, 8, 16, 32, 60]
    assert _BACKOFF_SEQUENCE[-1] == 60  # max interval
