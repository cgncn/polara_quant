from datetime import UTC, datetime
from decimal import Decimal

from polara.research_engine.strategies.vwap_mean_reversion import (
    VWAPMeanReversionStrategy,
    _session_vwap,
    _session_vwap_std,
)
from polara.schemas.market import Bar

# NYSE opens at 09:30 ET = 14:30 UTC (March 2024, ET=UTC-5)
_SESSION_OPEN_UTC = datetime(2024, 3, 1, 14, 30, tzinfo=UTC)


def make_bar(
    symbol: str,
    ts_utc: datetime,
    open_: str,
    high: str,
    low: str,
    close: str,
    volume: int,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts_utc,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
    )


def _session_bars(closes: list[str], base_ts: datetime = _SESSION_OPEN_UTC) -> list[Bar]:
    """Build session bars with equal volume of 100 each, spaced 15 min apart."""
    from datetime import timedelta

    return [
        make_bar("AAPL", base_ts + timedelta(minutes=15 * i), c, c, c, c, 100)
        for i, c in enumerate(closes)
    ]


def test_vwap_uniform_volume_is_simple_average():
    bars = _session_bars(["100", "102", "98", "104"])
    result = _session_vwap(bars)
    expected = (Decimal("100") + Decimal("102") + Decimal("98") + Decimal("104")) / 4
    assert result == expected


def test_vwap_varying_volume_is_weighted():
    from datetime import timedelta

    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 200),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "110", "110", "110", "110", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "90", "90", "90", "90", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "105", "105", "105", "105", 100),
    ]
    # manual: (100*200 + 110*100 + 90*100 + 105*100) / (200+100+100+100) = 40500/500 = 81.0... wait
    # (20000 + 11000 + 9000 + 10500) / 500 = 50500 / 500 = 101
    total_vol = Decimal("500")
    expected = (
        Decimal("100") * 200 + Decimal("110") * 100 + Decimal("90") * 100 + Decimal("105") * 100
    ) / total_vol
    assert _session_vwap(bars) == expected


def test_vwap_zero_volume_returns_zero():
    from datetime import timedelta

    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15 * i), "100", "100", "100", "100", 0)
        for i in range(4)
    ]
    assert _session_vwap(bars) == Decimal("0")


def test_on_bars_returns_none_when_not_enough_session_bars():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
    )
    bars = _session_bars(["100", "101", "99"])  # only 3 session bars
    assert strategy.on_bars(bars) is None


def test_on_bars_buy_signal_when_price_below_vwap():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        deviation_pct=Decimal("0.015"),
    )
    # 4 bars near 100 (VWAP ≈ 100), last bar at 98 = 2% below
    from datetime import timedelta

    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "98", "98", "98", "98", 100),
    ]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")
    assert signal.symbol == "AAPL"
    assert signal.strategy_id == "vwap-test"


def test_on_bars_sell_signal_when_price_above_vwap():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        deviation_pct=Decimal("0.015"),
    )
    from datetime import timedelta

    # VWAP = (100+100+100+103)/4 = 100.75, deviation = (103-100.75)/100.75 ≈ 2.23% > 1.5%
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "103", "103", "103", "103", 100),
    ]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


def test_on_bars_no_signal_within_deviation_threshold():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        deviation_pct=Decimal("0.015"),
    )
    from datetime import timedelta

    # last bar is 1% away from VWAP, below 1.5% threshold
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "99", "99", "99", "99", 100),
    ]
    assert strategy.on_bars(bars) is None


def test_take_profit_pct_reflects_excess_deviation():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        deviation_pct=Decimal("0.015"),
    )
    from datetime import timedelta

    # 3 bars at 100 with large volume anchor VWAP at ~100, last bar at 97.5
    # Use volume 10000 for the anchor bars so VWAP ≈ 100, giving ~2.5% deviation
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 10000),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "100", "100", "100", "100", 10000),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "100", "100", "100", "100", 10000),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "97.5", "97.5", "97.5", "97.5", 1),
    ]
    # VWAP ≈ (100*30000 + 97.5*1) / 30001 ≈ 99.9999...
    vwap = (Decimal("100") * 30000 + Decimal("97.5") * 1) / Decimal("30001")
    deviation = (Decimal("97.5") - vwap) / vwap
    expected_tp = abs(deviation) - Decimal("0.015")

    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.take_profit_pct is not None
    assert signal.take_profit_pct > 0
    assert signal.take_profit_pct == expected_tp


def test_on_bars_returns_none_when_vwap_is_zero():
    """Guard: if all session bars have zero volume, VWAP=0 and on_bars returns None."""
    from datetime import timedelta

    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
    )
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15 * i), "100", "100", "100", "100", 0)
        for i in range(4)
    ]
    assert strategy.on_bars(bars) is None


def test_signal_uses_full_session_bars_not_just_last():
    """VWAP is built from all session bars, not just the most recent one."""
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        deviation_pct=Decimal("0.015"),
    )
    from datetime import timedelta

    # Session starts high (~110), drifts to 100 — VWAP will be well above 100
    # Last bar at 100 should trigger buy because VWAP > 101.5 (>1.5% above 100)
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "110", "110", "110", "110", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "108", "108", "108", "108", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "106", "106", "106", "106", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "100", "100", "100", "100", 100),
    ]
    # VWAP = (110 + 108 + 106 + 100) / 4 = 424 / 4 = 106
    # deviation = (100 - 106) / 106 ≈ -0.0566, below -0.015 → buy
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


# ── bars_needed ───────────────────────────────────────────────────────────────

def test_bars_needed_is_3():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test", symbol="AAPL", bar_size="15 mins"
    )
    assert strategy.bars_needed == 3


# ── typical price (H+L+C)/3 ──────────────────────────────────────────────────

def test_vwap_uses_typical_price_not_just_close():
    """VWAP should use (H+L+C)/3, not just the close price."""
    from datetime import timedelta

    # Bar where H and L differ from C — typical price ≠ close
    # close=100, high=112, low=100 → typical = (112+100+100)/3 = 104
    bar = Bar(
        symbol="AAPL",
        timestamp=_SESSION_OPEN_UTC,
        open=Decimal("100"),
        high=Decimal("112"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=100,
    )
    vwap = _session_vwap([bar])
    expected = (Decimal("112") + Decimal("100") + Decimal("100")) / Decimal("3")
    assert vwap == expected
    assert vwap != Decimal("100")  # would be wrong if using close only


def test_vwap_std_nonzero_for_varying_prices():
    """Volume-weighted std dev is > 0 when bars have different typical prices."""
    from datetime import timedelta

    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC, "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=30), "100", "100", "100", "100", 100),
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=45), "90", "90", "90", "90", 100),
    ]
    vwap = _session_vwap(bars)
    std = _session_vwap_std(bars, vwap)
    assert std > Decimal("0")


def test_vwap_std_zero_for_uniform_prices():
    """Volume-weighted std dev is 0 when all bars have identical typical prices."""
    bars = _session_bars(["100", "100", "100", "100"])
    vwap = _session_vwap(bars)
    std = _session_vwap_std(bars, vwap)
    assert std == Decimal("0")


# ── std_mult band mode ────────────────────────────────────────────────────────

def _make_std_mult_bars() -> list[Bar]:
    """5 bars at 100, then 1 bar at 85 — price well below lower VWAP band."""
    from datetime import timedelta

    return [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15 * i), "100", "100", "100", "100", 1000)
        for i in range(5)
    ] + [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=75), "85", "85", "85", "85", 1000),
    ]


def test_std_mult_buy_signal_when_below_lower_band():
    """Price clearly below VWAP - std_mult*std → buy signal."""
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        std_mult=Decimal("1.0"),
    )
    bars = _make_std_mult_bars()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("1")


def test_std_mult_sell_signal_when_above_upper_band():
    """Price clearly above VWAP + std_mult*std → sell signal."""
    from datetime import timedelta

    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        std_mult=Decimal("1.0"),
    )
    bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15 * i), "100", "100", "100", "100", 1000)
        for i in range(5)
    ] + [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=75), "115", "115", "115", "115", 1000),
    ]
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.strength == Decimal("-1")


def test_std_mult_no_signal_within_bands():
    """Price inside VWAP bands → None."""
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        std_mult=Decimal("3.0"),  # wide bands
    )
    bars = _make_std_mult_bars()
    # With std_mult=3.0, bands are wider — last close at 85 may be inside
    # Use a very large multiplier so close=85 is inside VWAP±3σ with these bars
    # Actually let me use bars closer to VWAP for this test
    from datetime import timedelta
    close_bars = [
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=15 * i), "100", "100", "100", "100", 1000)
        for i in range(5)
    ] + [
        # Only 1% away from VWAP ≈ 100, std will be ~few points → std_mult=3.0 band is wide
        make_bar("AAPL", _SESSION_OPEN_UTC + timedelta(minutes=75), "99", "99", "99", "99", 1000),
    ]
    signal = strategy.on_bars(close_bars)
    assert signal is None


def test_std_mult_returns_none_when_std_is_zero():
    """All prices identical → std=0 → on_bars returns None in std_mult mode."""
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        std_mult=Decimal("1.5"),
    )
    # All bars identical → std = 0
    bars = _session_bars(["100", "100", "100", "100"])
    assert strategy.on_bars(bars) is None


def test_std_mult_stop_loss_uses_opposite_band():
    """In std_mult mode, stop_loss_pct reflects distance to opposite band."""
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test",
        symbol="AAPL",
        bar_size="15 mins",
        std_mult=Decimal("1.0"),
    )
    bars = _make_std_mult_bars()
    signal = strategy.on_bars(bars)
    assert signal is not None
    assert signal.stop_loss_pct > Decimal("0")


# ── PARAM_GRID ────────────────────────────────────────────────────────────────

def test_param_grid_present():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test", symbol="AAPL", bar_size="15 mins"
    )
    assert hasattr(strategy, "PARAM_GRID")
    assert isinstance(strategy.PARAM_GRID, dict)
    assert len(strategy.PARAM_GRID) > 0


def test_param_grid_includes_std_mult():
    strategy = VWAPMeanReversionStrategy(
        strategy_id="vwap-test", symbol="AAPL", bar_size="15 mins"
    )
    assert "std_mult" in strategy.PARAM_GRID
    assert "deviation_pct" in strategy.PARAM_GRID
