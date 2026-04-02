"""IBClient — owns the ib_async connection to IB Gateway.

Nothing outside broker/ should import from this module directly.
All external access goes through adapter.py.
"""
import asyncio
import logging
from typing import Any

from ib_async import IB

logger = logging.getLogger(__name__)

_BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 32, 60]  # seconds


class IBClient:
    """Manages a single persistent ib_async connection to IB Gateway.

    Usage (via FastAPI lifespan):
        client = IBClient(host="ib-gateway", port=4003, client_id=1)
        await client.connect()
        app.state.ib_client = client
        ...
        await client.disconnect()
    """

    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()
        self._reconnect_task: asyncio.Task[Any] | None = None
        self._shutdown = False

        self._ib.disconnectedEvent += self._on_disconnected

    # ── public API ─────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._ib.isConnected()

    @property
    def ib(self) -> IB:
        """Raw ib_async IB instance — adapter.py only."""
        return self._ib

    async def connect(self) -> None:
        """Attempt initial connection. Logs warning and returns if unreachable."""
        self._shutdown = False
        if self._ib.isConnected():
            return
        await self._try_connect()

    async def disconnect(self) -> None:
        """Clean shutdown — cancels reconnect task then disconnects."""
        self._shutdown = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._ib.isConnected():
            self._ib.disconnect()
        logger.info("IBClient disconnected")

    # ── internal ───────────────────────────────────────────────────────────────

    async def _try_connect(self) -> None:
        try:
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=10,
            )
            logger.info(
                "IBClient connected to %s:%s (clientId=%s)",
                self._host,
                self._port,
                self._client_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IBClient could not connect to %s:%s — %s. "
                "Endpoints will return 503 until connected.",
                self._host,
                self._port,
                exc,
            )

    def _on_disconnected(self) -> None:
        if self._shutdown:
            return
        logger.warning("IBClient disconnected — scheduling reconnect")
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        for delay in _BACKOFF_SEQUENCE:
            logger.info("IBClient reconnect attempt in %ss…", delay)
            await asyncio.sleep(delay)
            if self._shutdown:
                return
            await self._try_connect()
            if self._ib.isConnected():
                logger.info("IBClient reconnected successfully")
                return
        # After exhausting sequence, keep retrying at max interval
        while not self._shutdown and not self._ib.isConnected():
            await asyncio.sleep(_BACKOFF_SEQUENCE[-1])
            if self._shutdown:
                return
            await self._try_connect()
            if self._ib.isConnected():
                logger.info("IBClient reconnected successfully")
                return
