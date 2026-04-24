"""IBFetcher — wraps ib_async historical data and quote requests.

All float values from ib_async are converted to Decimal at this boundary.
"""
from datetime import UTC, datetime
from decimal import Decimal

from ib_async import IB, Contract

from polara.schemas.market import Bar, Quote

# Mapping from bar_size to approximate minutes per bar.
# Used to calculate a durationStr long enough to cover n bars.
_BAR_SIZE_MINUTES: dict[str, int] = {
    "1 min": 1,
    "5 mins": 5,
    "15 mins": 15,
    "30 mins": 30,
    "1 hour": 60,
    "1 day": 1440,
}


def _duration_for_n_bars(n: int, bar_size: str) -> str:
    """Return an IB durationStr that covers at least n bars of bar_size."""
    minutes = _BAR_SIZE_MINUTES.get(bar_size, 5)
    total_minutes = n * minutes * 2  # 2x buffer
    if total_minutes <= 1440:
        return f"{max(1, total_minutes // 60 + 1)} D"
    days = total_minutes // 1440 + 1
    if days <= 30:
        return f"{days} D"
    return f"{days // 30 + 1} M"


def _parse_ib_datetime(date_str: str | datetime) -> datetime:
    """Parse IB bar date — accepts either a string (YYYYMMDD HH:MM:SS or YYYYMMDD)
    or a datetime object (returned by newer ib_async versions, may be non-UTC)."""
    if isinstance(date_str, datetime):
        if date_str.tzinfo is None:
            return date_str.replace(tzinfo=UTC)
        return date_str.astimezone(UTC)
    date_str = date_str.strip()
    if " " in date_str:
        dt = datetime.strptime(date_str, "%Y%m%d %H:%M:%S")
    else:
        dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.replace(tzinfo=UTC)


class IBFetcher:
    """Fetches bars and quotes from IB Gateway via ib_async."""

    def __init__(self, ib: IB) -> None:
        self._ib = ib

    def _make_contract(self, symbol: str) -> Contract:
        return Contract(symbol=symbol, secType="STK", exchange="SMART", currency="USD")

    async def fetch_bars(self, symbol: str, n: int, bar_size: str = "5 mins") -> list[Bar]:
        """Fetch last n bars for symbol. Returns Decimal prices, UTC datetimes."""
        contract = self._make_contract(symbol)
        duration = _duration_for_n_bars(n, bar_size)
        raw_bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        bars = [
            Bar(
                symbol=symbol,
                timestamp=_parse_ib_datetime(b.date),
                open=Decimal(str(b.open)),
                high=Decimal(str(b.high)),
                low=Decimal(str(b.low)),
                close=Decimal(str(b.close)),
                volume=int(b.volume),
            )
            for b in raw_bars
        ]
        # Return only the last n bars (IB may return more due to duration rounding)
        return bars[-n:] if len(bars) > n else bars

    async def fetch_quote(self, symbol: str) -> Quote:
        """Fetch live bid/ask for symbol."""
        contract = self._make_contract(symbol)
        tickers = await self._ib.reqTickersAsync(contract)
        if not tickers:
            raise ValueError(f"No ticker data returned for {symbol}")
        t = tickers[0]
        return Quote(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            bid=Decimal(str(t.bid)),
            ask=Decimal(str(t.ask)),
            bid_size=int(t.bidSize),
            ask_size=int(t.askSize),
        )
