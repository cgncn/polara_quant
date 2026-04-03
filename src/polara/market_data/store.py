"""BarStore — DuckDB-backed storage for OHLCV bars.

Prices stored as DECIMAL(20, 10); timestamps as VARCHAR ISO-8601 UTC strings.
"""
from datetime import UTC, datetime
from decimal import Decimal

import duckdb

from polara.schemas.market import Bar

_CREATE_BARS_TABLE = """
CREATE TABLE IF NOT EXISTS bars (
    symbol      VARCHAR NOT NULL,
    timestamp   VARCHAR NOT NULL,
    open        DECIMAL(20, 10) NOT NULL,
    high        DECIMAL(20, 10) NOT NULL,
    low         DECIMAL(20, 10) NOT NULL,
    close       DECIMAL(20, 10) NOT NULL,
    volume      BIGINT NOT NULL,
    bar_size    VARCHAR NOT NULL,
    PRIMARY KEY (symbol, timestamp, bar_size)
)
"""

_UPSERT_BAR = """
INSERT INTO bars (symbol, timestamp, open, high, low, close, volume, bar_size)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, timestamp, bar_size) DO UPDATE SET
    open   = EXCLUDED.open,
    high   = EXCLUDED.high,
    low    = EXCLUDED.low,
    close  = EXCLUDED.close,
    volume = EXCLUDED.volume
"""

_QUERY_BARS = """
SELECT symbol, timestamp, open, high, low, close, volume
FROM bars
WHERE symbol = ? AND bar_size = ?
ORDER BY timestamp DESC
LIMIT ?
"""


class BarStore:
    """Persists and retrieves OHLCV bars using DuckDB."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with duckdb.connect(db_path) as conn:
            conn.execute(_CREATE_BARS_TABLE)

    def upsert(self, bars: list[Bar], bar_size: str) -> None:
        """Insert or update bars. Deduplicates on (symbol, timestamp, bar_size)."""
        if not bars:
            return
        rows = [
            (
                b.symbol,
                b.timestamp.isoformat(),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
                int(b.volume),
                bar_size,
            )
            for b in bars
        ]
        with duckdb.connect(self._db_path) as conn:
            conn.executemany(_UPSERT_BAR, rows)

    def query(self, symbol: str, n: int, bar_size: str) -> list[Bar]:
        """Return the n most recent bars for symbol, ordered oldest-first."""
        with duckdb.connect(self._db_path) as conn:
            rows = conn.execute(_QUERY_BARS, [symbol, bar_size, n]).fetchall()
        if not rows:
            return []
        bars = [
            Bar(
                symbol=row[0],
                timestamp=datetime.fromisoformat(row[1]).replace(tzinfo=UTC)
                if datetime.fromisoformat(row[1]).tzinfo is None
                else datetime.fromisoformat(row[1]),
                open=Decimal(str(row[2])),
                high=Decimal(str(row[3])),
                low=Decimal(str(row[4])),
                close=Decimal(str(row[5])),
                volume=int(row[6]),
            )
            for row in rows
        ]
        # Results are DESC from DB; reverse to oldest-first for strategy consumption
        return list(reversed(bars))
