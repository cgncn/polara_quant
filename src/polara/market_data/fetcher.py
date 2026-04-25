"""IBFetcher — wraps CPClient historical data and quote requests.

All float values from the CP API are converted to Decimal at this boundary.
"""
from datetime import UTC, datetime
from decimal import Decimal

from polara.broker.cp_client import CPClient
from polara.schemas.market import Bar, Quote

_BAR_SIZE_MAP: dict[str, str] = {
    "1 min": "1min",
    "5 mins": "5mins",
    "15 mins": "15mins",
    "30 mins": "30mins",
    "1 hour": "1h",
    "1 day": "1d",
}

_MINUTES_PER_BAR: dict[str, int] = {
    "1 min": 1,
    "5 mins": 5,
    "15 mins": 15,
    "30 mins": 30,
    "1 hour": 60,
    "1 day": 1440,
}


def _cp_period(n: int, bar_size: str) -> str:
    """Return CP API period string covering at least n bars (2× buffer)."""
    minutes = _MINUTES_PER_BAR.get(bar_size, 5)
    total_minutes = n * minutes * 2
    if total_minutes <= 1440:
        return f"{max(1, total_minutes // 60 + 1)}d"
    days = total_minutes // 1440 + 1
    if days <= 30:
        return f"{days}d"
    months = days // 30 + 1
    if months <= 12:
        return f"{months}m"
    years = months // 12 + 1
    return f"{years}y"


class IBFetcher:
    """Fetches bars and quotes from IBKR CP Gateway via CPClient."""

    def __init__(self, cp_client: CPClient) -> None:
        self._cp = cp_client

    async def fetch_bars(self, symbol: str, n: int, bar_size: str = "5 mins") -> list[Bar]:
        """Fetch last n bars for symbol. Returns Decimal prices, UTC datetimes."""
        conid = await self._cp.get_conid(symbol)
        cp_bar = _BAR_SIZE_MAP.get(bar_size, "5mins")
        period = _cp_period(n, bar_size)
        resp = await self._cp.historical_bars(conid, period=period, bar=cp_bar)
        raw_data: list[dict] = resp.get("data", [])
        bars = [
            Bar(
                symbol=symbol,
                timestamp=datetime.fromtimestamp(d["t"] / 1000, tz=UTC),
                open=Decimal(str(d["o"])),
                high=Decimal(str(d["h"])),
                low=Decimal(str(d["l"])),
                close=Decimal(str(d["c"])),
                volume=int(d.get("v", 0)),
            )
            for d in raw_data
        ]
        return bars[-n:] if len(bars) > n else bars

    async def fetch_quote(self, symbol: str) -> Quote:
        """Fetch live bid/ask for symbol via market snapshot."""
        conid = await self._cp.get_conid(symbol)
        snapshots = await self._cp.market_snapshot([conid])
        if not snapshots:
            raise ValueError(f"No snapshot data returned for {symbol}")
        snap = snapshots[0]
        bid_raw = snap.get("84")
        ask_raw = snap.get("86")
        if bid_raw is None or ask_raw is None:
            raise ValueError(f"Bid/ask not available in snapshot for {symbol}")
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            bid=Decimal(str(bid_raw)),
            ask=Decimal(str(ask_raw)),
            bid_size=int(snap.get("88", 0)),
            ask_size=int(snap.get("85", 0)),
        )
