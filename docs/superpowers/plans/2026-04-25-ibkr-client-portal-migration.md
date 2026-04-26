# IBKR Client Portal REST API Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ib_async` / IB Gateway (Java GUI + IBC) with the IBKR Client Portal REST API so the trading system runs headlessly in the cloud without GUI-based 2FA.

**Architecture:** A new `CPClient` HTTP client wraps all REST calls to the Client Portal Gateway and owns the session tickle loop and conid cache. `BrokerAdapter` and `IBFetcher` are updated in-place to call `CPClient` instead of `ib_async`. The rest of the stack (OrderManager, StrategyScheduler, API routes, DB schema) is untouched.

**Tech Stack:** `httpx.AsyncClient` (HTTPS, `verify=False` for self-signed cert), IBKR Client Portal Gateway JAR (Java 17), Docker, existing FastAPI + SQLAlchemy.

---

## File Map

| Action | File | Purpose |
|---|---|---|
| **CREATE** | `docker/cp-gateway/Dockerfile` | Containerises the Client Portal Gateway JAR |
| **CREATE** | `docker/cp-gateway/conf.yaml` | Gateway config (port, SSL, CORS) |
| **CREATE** | `src/polara/broker/cp_client.py` | HTTP client: session, tickle loop, conid cache, all REST calls |
| **MODIFY** | `src/polara/broker/adapter.py` | Replace every `ib_async` call with `CPClient` methods |
| **MODIFY** | `src/polara/broker/client.py` | Replace `IBClient` body with a thin shim that holds `CPClient` |
| **MODIFY** | `src/polara/market_data/fetcher.py` | Replace `reqHistoricalDataAsync` / `reqTickersAsync` with REST |
| **MODIFY** | `src/polara/api/main.py` | Boot `CPClient` instead of `IBClient`; wire into lifespan |
| **MODIFY** | `docker-compose.yml` | Replace `ib-gateway` service with `cp-gateway`; update env vars |
| **MODIFY** | `pyproject.toml` | Move `httpx` to production deps; remove `ib-async` |
| **CREATE** | `tests/test_cp_client.py` | Unit tests for CPClient (httpx mocked with respx) |
| **MODIFY** | `tests/test_broker_adapter.py` | Replace ib_async mocks with CPClient mocks |
| **MODIFY** | `tests/test_broker_client.py` | Replace IBClient tests with CPClient startup/tickle tests |

---

## Task 1: Docker — Client Portal Gateway container

**Files:**
- Create: `docker/cp-gateway/Dockerfile`
- Create: `docker/cp-gateway/conf.yaml`
- Create: `docker/cp-gateway/.gitignore`

### Background
The IBKR Client Portal Gateway is a Java JAR. The user must download `clientportal.gw.zip` from:
https://www.interactivebrokers.com/en/trading/ib-api.php#cpapi1
and place it at `docker/cp-gateway/clientportal.gw.zip` **before building**.

- [ ] **Step 1: Create the directory structure**
```bash
mkdir -p docker/cp-gateway
```

- [ ] **Step 2: Create the Dockerfile**

```dockerfile
# docker/cp-gateway/Dockerfile
FROM eclipse-temurin:17-jre-alpine

RUN apk add --no-cache unzip bash curl

WORKDIR /app

# User must place clientportal.gw.zip here before building
COPY clientportal.gw.zip .
RUN unzip -q clientportal.gw.zip && rm clientportal.gw.zip

COPY conf.yaml root/conf.yaml

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
  CMD curl -sk https://localhost:5000/v1/api/iserver/auth/status | grep -q '"connected"' || exit 1

CMD ["bin/run.sh", "root/conf.yaml"]
```

- [ ] **Step 3: Create conf.yaml**

```yaml
# docker/cp-gateway/conf.yaml
listenPort: 5000
listenSsl: true
sslCert: ""
sslPwd: ""
proxyRemoteSsl: true
ip: "0.0.0.0"
```

- [ ] **Step 4: Create .gitignore** (the zip is too large to commit)

```
clientportal.gw.zip
```

- [ ] **Step 5: Verify the directory layout**
```bash
ls docker/cp-gateway/
# Expected: Dockerfile  conf.yaml  .gitignore
# (clientportal.gw.zip present but gitignored)
```

---

## Task 2: docker-compose.yml — replace ib-gateway with cp-gateway

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Read the current docker-compose**
```bash
cat docker-compose.yml
```

- [ ] **Step 2: Replace the `ib-gateway` service block**

Remove the entire `ib-gateway` service and add:

```yaml
  cp-gateway:
    build:
      context: docker/cp-gateway
    ports:
      - "5000:5000"
    volumes:
      - cp-jts:/root
    environment:
      - TZ=America/New_York
    restart: unless-stopped
```

- [ ] **Step 3: Update the `polara-api` service**

Change:
```yaml
    environment:
      - IB_HOST=ib-gateway
      - IB_PORT=4003
      - IB_CLIENT_ID=1
```
To:
```yaml
    environment:
      - CP_GATEWAY_URL=https://cp-gateway:5000/v1/api
```

Remove the `depends_on: ib-gateway` line and replace with `depends_on: cp-gateway`.

- [ ] **Step 4: Update volumes section**

Remove `ib-jts` volume, add:
```yaml
volumes:
  cp-jts:
```

- [ ] **Step 5: Verify compose is valid**
```bash
docker compose config --quiet && echo "OK"
```

---

## Task 3: pyproject.toml — swap dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current deps**
```bash
cat pyproject.toml
```

- [ ] **Step 2: Move httpx to production, remove ib-async**

In `[project] dependencies`, remove:
```
"ib-async>=2.1,<3",
```

Add:
```
"httpx>=0.27",
```

In `[project.optional-dependencies] dev`, remove the `httpx` entry (it's now in prod).

- [ ] **Step 3: Add respx for mocking in dev**

In `[project.optional-dependencies] dev`, add:
```
"respx>=0.21",
```

- [ ] **Step 4: Sync deps**
```bash
uv sync
```
Expected: ib-async removed, httpx in production env.

---

## Task 4: Create `CPClient`

**Files:**
- Create: `src/polara/broker/cp_client.py`
- Test: `tests/test_cp_client.py`

### Background
`CPClient` is the single HTTP adapter for the IBKR Client Portal Gateway REST API. It:
- Maintains an `httpx.AsyncClient` with SSL verification disabled (self-signed cert)
- Runs a background tickle loop (heartbeat every 55 s to keep session alive)
- Caches `account_id` and symbol→conid lookups
- Handles the order confirmation reply dialog automatically

All REST responses are raw dicts/lists — parsing into domain types happens in `BrokerAdapter`.

- [ ] **Step 1: Write failing tests first**

```python
# tests/test_cp_client.py
import pytest
import respx
import httpx
from decimal import Decimal
from polara.broker.cp_client import CPClient, CPAuthError


BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def client():
    return CPClient(base_url=BASE)


@respx.mock
@pytest.mark.asyncio
async def test_start_fetches_account_id(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU123456", "type": "individual"}])
    )
    await client.start()
    assert client.account_id == "DU123456"
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_auth_status_returns_dict(client):
    respx.get(f"{BASE}/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True, "connected": True})
    )
    await client.start()
    # skip fetching account for this test
    client._account_id = "DU123456"
    status = await client.auth_status()
    assert status["authenticated"] is True
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_get_conid_caches_result(client):
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "488867728", "symbol": "PLTR"}])
    )
    await client.start()
    client._account_id = "DU123456"
    conid = await client.get_conid("PLTR")
    assert conid == 488867728
    # Second call should use cache (mock only registered once)
    conid2 = await client.get_conid("PLTR")
    assert conid2 == 488867728
    await client.stop()


@respx.mock
@pytest.mark.asyncio
async def test_place_orders_handles_confirmation(client):
    acc = "DU123456"
    respx.post(f"{BASE}/iserver/account/{acc}/orders").mock(
        return_value=httpx.Response(200, json=[{"id": "reply123", "message": ["Confirm?"]}])
    )
    respx.post(f"{BASE}/iserver/reply/reply123").mock(
        return_value=httpx.Response(200, json=[{"order_id": "987", "order_status": "PreSubmitted"}])
    )
    await client.start()
    client._account_id = acc
    result = await client.place_orders([{"conid": 488867728, "orderType": "MKT", "side": "BUY", "quantity": 1, "tif": "DAY"}])
    assert result[0]["order_id"] == "987"
    await client.stop()
```

- [ ] **Step 2: Run to confirm they fail**
```bash
uv run pytest tests/test_cp_client.py -v 2>&1 | head -30
```
Expected: ImportError (module doesn't exist yet).

- [ ] **Step 3: Implement `cp_client.py`**

```python
# src/polara/broker/cp_client.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class CPAuthError(Exception):
    pass


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

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._account_id is not None

    @property
    def account_id(self) -> str:
        if not self._account_id:
            raise CPAuthError("Not authenticated — visit https://<host>:5000 to log in")
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
                await self._http.post(f"{self._base}/tickle")  # type: ignore[union-attr]
            except Exception as exc:
                log.warning("tickle failed: %s", exc)

    async def _fetch_account_id(self) -> None:
        accounts = await self._get("/portfolio/accounts")
        if not accounts:
            raise CPAuthError("No accounts returned — gateway not authenticated")
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
        # Handle confirmation dialog: {"id": "...", "message": [...]}
        if isinstance(resp, list) and resp and "message" in resp[0] and "id" in resp[0]:
            confirm_id = resp[0]["id"]
            resp = await self._post(f"/iserver/reply/{confirm_id}", {"confirmed": True})
        return resp if isinstance(resp, list) else [resp]

    async def cancel_order(self, ib_order_id: int) -> dict[str, Any]:
        return await self._delete(f"/iserver/account/{self.account_id}/order/{ib_order_id}")

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
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_cp_client.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**
```bash
git add src/polara/broker/cp_client.py tests/test_cp_client.py pyproject.toml
git commit -m "feat: add CPClient for IBKR Client Portal REST API"
```

---

## Task 5: Replace `IBClient` with a shim that holds `CPClient`

**Files:**
- Modify: `src/polara/broker/client.py`
- Modify: `tests/test_broker_client.py`

### Background
`BrokerAdapter` and `main.py` currently import `IBClient`. Rather than rename every reference now, replace `IBClient`'s internals so it holds a `CPClient`. This is a pure swap — the public surface (`connected`, `ib` property) is removed (nothing outside `adapter.py` uses `.ib` directly after the next task).

- [ ] **Step 1: Write failing test**

```python
# tests/test_broker_client.py  (replace entire file)
import pytest
import respx
import httpx
from polara.broker.client import IBClient  # kept for backward compat import


BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def client():
    return IBClient(cp_gateway_url=BASE)


@respx.mock
@pytest.mark.asyncio
async def test_connect_fetches_account(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999", "type": "individual"}])
    )
    await client.connect()
    assert client.connected is True
    assert client.cp.account_id == "DU999"
    await client.disconnect()


@respx.mock
@pytest.mark.asyncio
async def test_disconnect_stops_tickle(client):
    respx.get(f"{BASE}/portfolio/accounts").mock(
        return_value=httpx.Response(200, json=[{"accountId": "DU999", "type": "individual"}])
    )
    await client.connect()
    await client.disconnect()
    assert client.connected is False
```

- [ ] **Step 2: Run to confirm failure**
```bash
uv run pytest tests/test_broker_client.py -v 2>&1 | head -20
```

- [ ] **Step 3: Rewrite `client.py`**

```python
# src/polara/broker/client.py
from __future__ import annotations

import logging

from polara.broker.cp_client import CPClient

log = logging.getLogger(__name__)


class IBClient:
    """Backward-compatible wrapper — delegates to CPClient."""

    def __init__(self, cp_gateway_url: str = "https://cp-gateway:5000/v1/api") -> None:
        self._cp = CPClient(base_url=cp_gateway_url)

    @property
    def cp(self) -> CPClient:
        return self._cp

    @property
    def connected(self) -> bool:
        return self._cp.connected

    async def connect(self) -> None:
        await self._cp.start()

    async def disconnect(self) -> None:
        await self._cp.stop()
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_broker_client.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**
```bash
git add src/polara/broker/client.py tests/test_broker_client.py
git commit -m "refactor: replace IBClient internals with CPClient shim"
```

---

## Task 6: Migrate `BrokerAdapter` to use `CPClient`

**Files:**
- Modify: `src/polara/broker/adapter.py`
- Modify: `tests/test_broker_adapter.py`

### Background
Every method in `BrokerAdapter` currently calls `self._client.ib` (the raw `ib_async` IB instance). Replace each with `self._client.cp` (the `CPClient`). Key differences:
- No more `ib.positions()` synchronous call — use `await self._client.cp.positions()`
- No more `execDetailsEvent` / `orderStatusEvent` callbacks — replace with `_order_polling_loop()` background task
- Account summary response is a dict of `{tag: {amount, currency}}` not individual ib_async objects
- `Decimal` conversion still happens at the boundary

The `_register_callbacks()` method becomes `_start_polling()`.

- [ ] **Step 1: Write failing tests** (replace the mock structure in `tests/test_broker_adapter.py`)

Keep all existing test function names. Replace the `ib_mock` fixture with a `cp_mock` fixture:

```python
# tests/test_broker_adapter.py  — fixture section (top of file)
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from datetime import datetime, UTC
from uuid import UUID

from polara.broker.adapter import BrokerAdapter
from polara.broker.cp_client import CPClient
from polara.broker.schemas import AccountInfo, Position, BrokerStatus


BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def cp_client():
    client = CPClient(base_url=BASE)
    client._account_id = "DU123456"  # pre-authenticated
    return client


@pytest.fixture
def adapter(cp_client):
    from polara.broker.client import IBClient
    ib = IBClient(cp_gateway_url=BASE)
    ib._cp = cp_client
    return BrokerAdapter(client=ib, db_session_factory=AsyncMock())


@respx.mock
@pytest.mark.asyncio
async def test_get_broker_status_connected(adapter):
    respx.get(f"{BASE}/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True, "connected": True})
    )
    status = await adapter.get_broker_status()
    assert status.connected is True


@respx.mock
@pytest.mark.asyncio
async def test_get_account_returns_account_info(adapter):
    respx.get(f"{BASE}/portfolio/DU123456/summary").mock(
        return_value=httpx.Response(200, json={
            "netliquidation": {"amount": 10000.0, "currency": "USD"},
            "totalcashvalue": {"amount": 9500.0, "currency": "USD"},
            "unrealizedpnl": {"amount": 250.0, "currency": "USD"},
            "realizedpnl": {"amount": 100.0, "currency": "USD"},
        })
    )
    account = await adapter.get_account()
    assert account.net_liquidation == Decimal("10000.0")
    assert account.cash == Decimal("9500.0")


@respx.mock
@pytest.mark.asyncio
async def test_get_positions_returns_list(adapter):
    respx.get(f"{BASE}/portfolio/DU123456/positions/0").mock(
        return_value=httpx.Response(200, json=[
            {"contractDesc": "PLTR", "position": 10, "avgCost": 18.5, "unrealPnl": 50.0}
        ])
    )
    positions = await adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "PLTR"
    assert positions[0].quantity == Decimal("10")


@respx.mock
@pytest.mark.asyncio
async def test_place_order_returns_order_id(adapter, tmp_path):
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "488867728", "symbol": "PLTR"}])
    )
    respx.post(f"{BASE}/iserver/account/DU123456/orders").mock(
        return_value=httpx.Response(200, json=[{"order_id": "42", "order_status": "PreSubmitted"}])
    )
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    adapter._db_session_factory = MagicMock(return_value=db)

    from polara.broker.schemas import OrderRequest
    req = OrderRequest(symbol="PLTR", action="buy", quantity=Decimal("1"), order_type="market")
    order_id = await adapter.place_order(req, db)
    assert isinstance(order_id, UUID)
```

- [ ] **Step 2: Read current adapter to plan edits**
```bash
wc -l src/polara/broker/adapter.py
```

- [ ] **Step 3: Rewrite `get_broker_status()`**

Replace the existing method body (keep the signature):

```python
async def get_broker_status(self) -> BrokerStatus:
    try:
        status = await self._client.cp.auth_status()
        return BrokerStatus(
            connected=bool(status.get("authenticated")),
            ib_server_time=datetime.now(UTC),
            account_id=self._client.cp.account_id if self._client.connected else "",
        )
    except Exception:
        return BrokerStatus(
            connected=False,
            ib_server_time=datetime.now(UTC),
            account_id="",
        )
```

- [ ] **Step 4: Rewrite `get_account()`**

```python
async def get_account(self) -> AccountInfo:
    now = datetime.now(UTC)
    if self._account_cache and (now - self._account_cache_time).total_seconds() < 300:
        return self._account_cache  # type: ignore[return-value]

    summary = await self._client.cp.account_summary()

    def _d(key: str) -> Decimal:
        entry = summary.get(key, {})
        return Decimal(str(entry.get("amount", 0)))

    info = AccountInfo(
        net_liquidation=_d("netliquidation"),
        cash=_d("totalcashvalue"),
        unrealised_pnl=_d("unrealizedpnl"),
        realised_pnl=_d("realizedpnl"),
        currency="USD",
        timestamp=now,
    )
    self._account_cache = info
    self._account_cache_time = now
    return info
```

Ensure the cache attributes are initialised in `__init__`:
```python
self._account_cache: AccountInfo | None = None
self._account_cache_time: datetime = datetime.min.replace(tzinfo=UTC)
```

- [ ] **Step 5: Rewrite `get_positions()`**

```python
async def get_positions(self) -> list[Position]:
    data = await self._client.cp.positions()
    return [
        Position(
            symbol=p.get("contractDesc", p.get("ticker", "")),
            quantity=Decimal(str(p["position"])),
            avg_cost=Decimal(str(p["avgCost"])),
            unrealised_pnl=Decimal(str(p.get("unrealPnl", 0))),
            updated_at=datetime.now(UTC),
        )
        for p in data
        if p.get("position", 0) != 0
    ]
```

- [ ] **Step 6: Rewrite `place_order()`**

```python
async def place_order(self, req: OrderRequest, db: AsyncSession) -> UUID:  # type: ignore[name-defined]
    conid = await self._client.cp.get_conid(req.symbol)
    payload: dict[str, Any] = {
        "conid": conid,
        "orderType": "MKT" if req.order_type == "market" else "LMT",
        "side": req.action.upper(),
        "quantity": float(req.quantity),
        "tif": "DAY",
        "acctId": self._client.cp.account_id,
    }
    if req.order_type == "limit" and req.limit_price is not None:
        payload["price"] = float(req.limit_price)

    results = await self._client.cp.place_orders([payload])
    ib_order_id = int(results[0]["order_id"])

    order_id = uuid4()
    # persist to DB (same logic as before)
    await self._save_order(db, order_id, ib_order_id, req.symbol, req.action, req.quantity)
    return order_id
```

- [ ] **Step 7: Rewrite `place_bracket_order()`**

```python
async def place_bracket_order(
    self,
    symbol: str,
    action: str,
    quantity: Decimal,
    stop_loss_price: Decimal | None = None,
    take_profit_price: Decimal | None = None,
    db: AsyncSession | None = None,
) -> UUID:
    conid = await self._client.cp.get_conid(symbol)
    opposite = "SELL" if action.upper() == "BUY" else "BUY"
    parent_coid = str(uuid4())

    orders: list[dict[str, Any]] = [
        {
            "cOID": parent_coid,
            "conid": conid,
            "orderType": "MKT",
            "side": action.upper(),
            "quantity": float(quantity),
            "tif": "DAY",
            "acctId": self._client.cp.account_id,
        }
    ]
    if stop_loss_price is not None:
        orders.append({
            "parentId": parent_coid,
            "conid": conid,
            "orderType": "STP",
            "side": opposite,
            "auxPrice": float(stop_loss_price),
            "quantity": float(quantity),
            "tif": "GTC",
            "acctId": self._client.cp.account_id,
        })
    if take_profit_price is not None:
        orders.append({
            "parentId": parent_coid,
            "conid": conid,
            "orderType": "LMT",
            "side": opposite,
            "price": float(take_profit_price),
            "quantity": float(quantity),
            "tif": "GTC",
            "acctId": self._client.cp.account_id,
        })

    results = await self._client.cp.place_orders(orders)
    ib_order_id = int(results[0]["order_id"])

    order_id = uuid4()
    if db:
        await self._save_order(db, order_id, ib_order_id, symbol, action, quantity)
    return order_id
```

- [ ] **Step 8: Rewrite `cancel_order()`**

```python
async def cancel_order(self, order_id: UUID, db: AsyncSession) -> None:
    order = await self._load_order(db, order_id)  # existing helper
    if order is None:
        raise OrderNotFoundError(str(order_id))
    await self._client.cp.cancel_order(order.ib_order_id)
    await self._update_order_status_db(db, order_id, "Cancelled")
```

- [ ] **Step 9: Replace `_register_callbacks()` with `_start_polling()`**

Remove `_register_callbacks()`, `_on_exec_details()`, `_on_order_status()` and their helpers. Add an order polling loop:

```python
def start_polling(self) -> asyncio.Task[None]:
    return asyncio.create_task(self._order_polling_loop())

async def _order_polling_loop(self) -> None:
    while True:
        await asyncio.sleep(5)
        try:
            await self._sync_open_orders()
        except Exception as exc:
            log.warning("order poll error: %s", exc)

async def _sync_open_orders(self) -> None:
    resp = await self._client.cp.list_orders()
    orders_data = resp.get("orders") or []
    async with self._db_session_factory() as db:
        for o in orders_data:
            ib_id = o.get("orderId")
            status = o.get("status", "")
            if ib_id:
                await self._update_order_by_ib_id(db, int(ib_id), status)
```

- [ ] **Step 10: Run tests**
```bash
uv run pytest tests/test_broker_adapter.py -v
```
Expected: all adapter tests PASS.

- [ ] **Step 11: Commit**
```bash
git add src/polara/broker/adapter.py tests/test_broker_adapter.py
git commit -m "feat: migrate BrokerAdapter from ib_async to IBKR Client Portal REST API"
```

---

## Task 7: Migrate `IBFetcher` to use REST

**Files:**
- Modify: `src/polara/market_data/fetcher.py`

### Background
`IBFetcher.fetch_bars()` calls `ib.reqHistoricalDataAsync()`. The CP API equivalent is:
- `GET /iserver/marketdata/history?conid={}&period={}&bar={}&outsideRth=false`

Bar size mapping (ib_async → CP API):
- `"1 hour"` → `"1h"`
- `"1 day"` → `"1d"`

Period: we request the last 3 months: `"3m"`.

The response shape is `{"data": [{"t": ms_epoch, "o": float, "h": float, "l": float, "c": float, "v": int}]}`.

`fetch_quote()` maps to `client.cp.market_snapshot([conid])`.

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_market_data_fetcher.py (or create it)
import pytest
import respx
import httpx
from decimal import Decimal
from polara.market_data.fetcher import IBFetcher
from polara.broker.cp_client import CPClient


BASE = "https://cp-gateway:5000/v1/api"


@pytest.fixture
def fetcher():
    cp = CPClient(base_url=BASE)
    cp._account_id = "DU123456"
    return IBFetcher(cp_client=cp)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bars_returns_ohlcv(fetcher):
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "488867728", "symbol": "PLTR"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/history").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"t": 1704067200000, "o": 18.5, "h": 19.0, "l": 18.2, "c": 18.8, "v": 500000},
                {"t": 1704070800000, "o": 18.8, "h": 19.5, "l": 18.7, "c": 19.2, "v": 600000},
            ]
        })
    )
    bars = await fetcher.fetch_bars("PLTR", bar_size="1 hour", lookback_bars=2)
    assert len(bars) == 2
    assert bars[0].close == Decimal("18.8")
    assert bars[1].open == Decimal("18.8")


@respx.mock
@pytest.mark.asyncio
async def test_fetch_quote_returns_bid_ask(fetcher):
    respx.post(f"{BASE}/iserver/secdef/search").mock(
        return_value=httpx.Response(200, json=[{"conid": "488867728", "symbol": "PLTR"}])
    )
    respx.get(f"{BASE}/iserver/marketdata/snapshot").mock(
        return_value=httpx.Response(200, json=[
            {"conid": 488867728, "84": "18.50", "86": "18.55", "31": "18.52"}
        ])
    )
    quote = await fetcher.fetch_quote("PLTR")
    assert quote.bid == Decimal("18.50")
    assert quote.ask == Decimal("18.55")
```

- [ ] **Step 2: Run to confirm failure**
```bash
uv run pytest tests/test_market_data_fetcher.py -v 2>&1 | head -20
```

- [ ] **Step 3: Rewrite `IBFetcher`**

Read the current file first (`src/polara/market_data/fetcher.py`), then replace it with:

```python
# src/polara/market_data/fetcher.py
from __future__ import annotations

import logging
from datetime import datetime, UTC
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polara.broker.cp_client import CPClient

from polara.market_data.schemas import Bar, Quote  # adjust import to match actual schema paths

log = logging.getLogger(__name__)

_BAR_SIZE_MAP = {
    "1 hour": "1h",
    "1 day": "1d",
    "1 min": "1min",
    "5 mins": "5min",
    "30 mins": "30min",
}

_LOOKBACK_PERIOD = "3m"  # always fetch 3 months; caller slices to lookback_bars


class IBFetcher:
    def __init__(self, cp_client: CPClient) -> None:
        self._cp = cp_client

    async def fetch_bars(
        self,
        symbol: str,
        bar_size: str = "1 hour",
        lookback_bars: int = 50,
    ) -> list[Bar]:
        conid = await self._cp.get_conid(symbol)
        cp_bar = _BAR_SIZE_MAP.get(bar_size, "1h")
        resp = await self._cp.historical_bars(
            conid=conid,
            period=_LOOKBACK_PERIOD,
            bar=cp_bar,
            outside_rth=False,
        )
        raw = resp.get("data", [])
        bars = [
            Bar(
                time=datetime.fromtimestamp(d["t"] / 1000, tz=UTC),
                open=Decimal(str(d["o"])),
                high=Decimal(str(d["h"])),
                low=Decimal(str(d["l"])),
                close=Decimal(str(d["c"])),
                volume=int(d["v"]),
            )
            for d in raw
        ]
        return bars[-lookback_bars:] if lookback_bars else bars

    async def fetch_quote(self, symbol: str) -> Quote:
        conid = await self._cp.get_conid(symbol)
        snaps = await self._cp.market_snapshot([conid])
        s = snaps[0] if snaps else {}
        return Quote(
            symbol=symbol,
            bid=Decimal(str(s.get("84", 0))),
            ask=Decimal(str(s.get("86", 0))),
            last=Decimal(str(s.get("31", 0))),
            timestamp=datetime.now(UTC),
        )
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_market_data_fetcher.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/polara/market_data/fetcher.py tests/test_market_data_fetcher.py
git commit -m "feat: migrate IBFetcher from ib_async to IBKR Client Portal REST API"
```

---

## Task 8: Update `main.py` lifespan

**Files:**
- Modify: `src/polara/api/main.py`

### Background
`main.py` currently reads `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID` env vars and creates `IBClient(host, port, client_id)`. Replace with reading `CP_GATEWAY_URL` and creating `IBClient(cp_gateway_url=...)`. The `_register_callbacks()` call becomes `adapter.start_polling()`. The `IBFetcher` constructor now takes `cp_client=` instead of `ib=`.

- [ ] **Step 1: Read the lifespan section**
```bash
sed -n '30,110p' src/polara/api/main.py
```

- [ ] **Step 2: Replace env var reads**

Change:
```python
ib_host = os.environ.get("IB_HOST", "ib-gateway")
ib_port = int(os.environ.get("IB_PORT", "4003"))
ib_client_id = int(os.environ.get("IB_CLIENT_ID", "1"))
```
To:
```python
cp_gateway_url = os.environ.get("CP_GATEWAY_URL", "https://cp-gateway:5000/v1/api")
```

- [ ] **Step 3: Replace IBClient construction**

Change:
```python
ib_client = IBClient(host=ib_host, port=ib_port, client_id=ib_client_id)
await ib_client.connect()
```
To:
```python
ib_client = IBClient(cp_gateway_url=cp_gateway_url)
await ib_client.connect()
```

- [ ] **Step 4: Replace `_register_callbacks()` with `start_polling()`**

Change:
```python
adapter._register_callbacks()
```
To:
```python
polling_task = adapter.start_polling()
```

Add to shutdown:
```python
polling_task.cancel()
```

- [ ] **Step 5: Update IBFetcher construction**

Change:
```python
fetcher = IBFetcher(ib=ib_client.ib)
```
To:
```python
fetcher = IBFetcher(cp_client=ib_client.cp)
```

- [ ] **Step 6: Add auth status endpoint** (lets you check if gateway is logged in)

In `src/polara/api/routes/broker.py`, add after the existing `/broker/status` route:

```python
@router.get("/broker/auth")
async def get_auth_status(request: Request) -> dict:
    """Returns IBKR Client Portal Gateway auth status."""
    adapter: BrokerAdapter = request.app.state.broker_adapter
    return await adapter._client.cp.auth_status()
```

- [ ] **Step 7: Run all tests**
```bash
uv run pytest -x -q
```
Expected: all PASS (or near-all; fix any remaining import errors).

- [ ] **Step 8: Commit**
```bash
git add src/polara/api/main.py src/polara/api/routes/broker.py
git commit -m "feat: wire CPClient into FastAPI lifespan; add /broker/auth endpoint"
```

---

## Task 9: Full test suite + ruff

**Files:** no new files

- [ ] **Step 1: Run full test suite**
```bash
uv run pytest -v 2>&1 | tail -20
```
Expected: all green.

- [ ] **Step 2: Lint**
```bash
uv run ruff check src/
```
Expected: no errors.

- [ ] **Step 3: Final commit**
```bash
git add -A
git commit -m "chore: migrate broker layer from ib_async to IBKR Client Portal REST API"
```

---

## Task 10: First-time authentication (runtime, not code)

This task is operational — no code changes.

- [ ] **Step 1: Build and start cp-gateway**
```bash
docker compose build cp-gateway
docker compose up cp-gateway -d
docker compose logs cp-gateway -f
```
Wait for `Listening on port 5000`.

- [ ] **Step 2: Open the auth URL in your browser**

On your Mac, open:
```
https://localhost:5000
```
(Accept the self-signed cert warning.)
Log in with your IBKR credentials. Complete 2FA **in the browser** (IBKR will show IB Key / SMS options — this is more reliable than the mobile push that wasn't arriving).

- [ ] **Step 3: Verify auth via API**
```bash
curl -sk https://localhost:5000/v1/api/iserver/auth/status | python3 -m json.tool
```
Expected: `"authenticated": true, "connected": true`

- [ ] **Step 4: Start polara-api**
```bash
docker compose up polara-api -d
docker compose logs polara-api -f
```
Watch for: `CP Gateway account: DU...` log line.

- [ ] **Step 5: Smoke test**
```bash
curl http://localhost:8001/broker/auth
curl http://localhost:8001/broker/account
curl http://localhost:8001/strategy/list
```
Expected: authenticated account info and all strategies listed.

---

## Verification

End-to-end checklist:

1. `curl -sk https://localhost:5000/v1/api/iserver/auth/status` → `authenticated: true`
2. `curl http://localhost:8001/broker/status` → `connected: true`
3. `curl http://localhost:8001/broker/account` → non-zero `net_liquidation`
4. `curl http://localhost:8001/broker/positions` → JSON list (empty is fine for paper)
5. `curl http://localhost:8001/strategy/list` → 17 strategies including `bb-am`, `bb-rnr`, `bb-csl`
6. `uv run pytest -q` → all green
7. `docker compose logs polara-api` → no `CPAuthError`, tickle loop running silently

---

## Self-Review

**Spec coverage check:**
- ✅ Remove ib_async / IB Gateway — Task 3 (dep), Task 2 (docker)
- ✅ New REST client — Task 4 (CPClient)
- ✅ Auth + tickle — CPClient.start() + _tickle_loop()
- ✅ Account summary — Task 6 step 4
- ✅ Positions — Task 6 step 5
- ✅ Place order (market + limit) — Task 6 step 6
- ✅ Place bracket order — Task 6 step 7
- ✅ Cancel order — Task 6 step 8
- ✅ Order fill polling (replaces callbacks) — Task 6 step 9
- ✅ Historical bars — Task 7
- ✅ Live quotes — Task 7
- ✅ Docker compose swap — Task 2
- ✅ main.py wired — Task 8
- ✅ First-time auth flow documented — Task 10
