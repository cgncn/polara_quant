"""CPClient — async HTTP client for the IBKR Client Portal Gateway REST API.

All float values from the REST API are converted to Decimal at the boundary in
BrokerAdapter/IBFetcher. This module returns raw dicts/lists from the JSON responses.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class CPAuthError(Exception):
    """Raised when the CP Gateway is not authenticated or has no accounts."""


class CPClient:
    """Async HTTP client for the IBKR Client Portal Gateway REST API."""

    def __init__(self, base_url: str = "https://cp-gateway:5000/v1/api") -> None:
        self._base = base_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None
        self._account_id: str | None = None
        self._conid_cache: dict[str, int] = {}
        self._tickle_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._http = httpx.AsyncClient(verify=False, timeout=30.0)
        await self._fetch_account_id()
        self._tickle_task = asyncio.create_task(self._tickle_loop())

    async def stop(self) -> None:
        if self._tickle_task:
            self._tickle_task.cancel()
            try:
                await self._tickle_task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
            self._http = None
        self._account_id = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._account_id is not None

    @property
    def account_id(self) -> str:
        if not self._account_id:
            raise CPAuthError(
                "Not authenticated — visit https://<cp-gateway-host>:5000 to log in"
            )
        return self._account_id

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def auth_status(self) -> dict[str, Any]:
        return await self._get("/iserver/auth/status")

    async def _tickle_loop(self) -> None:
        while True:
            await asyncio.sleep(55)
            try:
                assert self._http is not None
                r = await self._http.post(f"{self._base}/tickle")
                r.raise_for_status()

                auth = await self._get("/iserver/auth/status")
                if not auth.get("authenticated"):
                    log.warning("CP Gateway session unauthenticated — attempting reauthentication")
                    await self._http.post(f"{self._base}/iserver/reauthenticate")
                    await asyncio.sleep(3)
                    await self._fetch_account_id()
                    log.info("CP Gateway reauthenticated successfully")

            except Exception as exc:
                log.warning("CP Gateway keepalive failed: %s — switching to reconnect mode", exc)
                self._account_id = None
                await self._reconnect_loop()

    async def _reconnect_loop(self) -> None:
        """Keep retrying until the CP Gateway session is restored."""
        delay = 15
        attempt = 0
        while True:
            attempt += 1
            await asyncio.sleep(delay)
            try:
                assert self._http is not None
                await self._http.post(f"{self._base}/iserver/reauthenticate")
                await asyncio.sleep(3)
                await self._fetch_account_id()
                log.info("CP Gateway reconnected on attempt %d", attempt)
                return
            except Exception as exc:
                log.warning("Reconnect attempt %d failed: %s", attempt, exc)
                delay = min(delay * 2, 120)

    async def _fetch_account_id(self) -> None:
        accounts = await self._get("/portfolio/accounts")
        if not accounts:
            raise CPAuthError("No accounts returned — CP Gateway not authenticated")
        self._account_id = accounts[0]["accountId"]
        log.info("CP Gateway account: %s", self._account_id)

    # ------------------------------------------------------------------
    # Contract lookup
    # ------------------------------------------------------------------

    async def get_conid(self, symbol: str) -> int:
        if symbol in self._conid_cache:
            return self._conid_cache[symbol]
        results = await self._post(
            "/iserver/secdef/search",
            {"symbol": symbol, "name": False, "secType": "STK"},
        )
        if not results:
            raise ValueError(f"No contract found for symbol {symbol!r}")
        conid = int(results[0]["conid"])
        self._conid_cache[symbol] = conid
        return conid

    # ------------------------------------------------------------------
    # Account / portfolio
    # ------------------------------------------------------------------

    async def account_summary(self) -> dict[str, Any]:
        return await self._get(f"/portfolio/{self.account_id}/summary")

    async def positions(self) -> list[dict[str, Any]]:
        return await self._get(f"/portfolio/{self.account_id}/positions/0")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def place_orders(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resp = await self._post(
            f"/iserver/account/{self.account_id}/orders",
            {"orders": orders},
        )
        # Handle confirmation dialog: [{"id": "...", "message": [...]}]
        if isinstance(resp, list) and resp and "message" in resp[0] and "id" in resp[0]:
            confirm_id = resp[0]["id"]
            resp = await self._post(f"/iserver/reply/{confirm_id}", {"confirmed": True})
        return resp if isinstance(resp, list) else [resp]

    async def cancel_order(self, ib_order_id: int) -> dict[str, Any]:
        return await self._delete(
            f"/iserver/account/{self.account_id}/order/{ib_order_id}"
        )

    async def list_orders(self) -> dict[str, Any]:
        return await self._get("/iserver/account/orders")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def historical_bars(
        self,
        conid: int,
        period: str,
        bar: str,
        outside_rth: bool = False,
    ) -> dict[str, Any]:
        return await self._get(
            "/iserver/marketdata/history",
            conid=conid,
            period=period,
            bar=bar,
            outsideRth=str(outside_rth).lower(),
        )

    async def market_snapshot(self, conids: list[int]) -> list[dict[str, Any]]:
        # fields: 31=last, 84=bid, 86=ask
        return await self._get(
            "/iserver/marketdata/snapshot",
            conids=",".join(str(c) for c in conids),
            fields="31,84,86",
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, **params: Any) -> Any:
        assert self._http is not None
        r = await self._http.get(f"{self._base}{path}", params=params or None)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        assert self._http is not None
        r = await self._http.post(f"{self._base}{path}", json=body)
        r.raise_for_status()
        return r.json()

    async def _delete(self, path: str) -> Any:
        assert self._http is not None
        r = await self._http.delete(f"{self._base}{path}")
        r.raise_for_status()
        return r.json()
