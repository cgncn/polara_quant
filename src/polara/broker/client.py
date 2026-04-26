"""IBClient — backward-compatible wrapper that delegates to CPClient.

Nothing outside broker/ should import from this module directly.
All external access goes through adapter.py.
"""
from __future__ import annotations

import logging

from polara.broker.cp_client import CPAuthError, CPClient

logger = logging.getLogger(__name__)


class IBClient:
    """Manages connection to the IBKR Client Portal Gateway via CPClient.

    Usage (via FastAPI lifespan):
        client = IBClient(cp_gateway_url="https://cp-gateway:5000/v1/api")
        await client.connect()
        app.state.ib_client = client
        ...
        await client.disconnect()
    """

    def __init__(self, cp_gateway_url: str = "https://cp-gateway:5000/v1/api") -> None:
        self._cp = CPClient(base_url=cp_gateway_url)

    @property
    def cp(self) -> CPClient:
        return self._cp

    @property
    def connected(self) -> bool:
        return self._cp.connected

    async def connect(self) -> None:
        """Start CP Gateway session; swallows auth error so API server can still start."""
        try:
            await self._cp.start()
        except CPAuthError as exc:
            logger.warning(
                "CP Gateway not authenticated yet — %s. "
                "Visit https://<cp-gateway-host>:5000 to log in.",
                exc,
            )
        except Exception as exc:
            logger.warning("CP Gateway connect failed: %s", exc)

    async def disconnect(self) -> None:
        await self._cp.stop()
        logger.info("IBClient disconnected")
