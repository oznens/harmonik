"""SMC bölge filtreleri (#4 Order Block · #5 FVG · #6 Liquidity Sweep) + skor."""
from __future__ import annotations

from terminal.detection.structure import (
    check_liquidity_sweep,
    find_fair_value_gaps,
    find_order_blocks,
)
from terminal.karakter.portfolio import format_smc_sweep, simulate_portfolio
from terminal.quality.smc import compute_smc


def _bar(o, h, l, c, t):
    return {"open_time": t, "close_time": t + 1, "open": o, "high": h,
            "low": l, "close": c, "volume": 100, "quote_volume": 1000}


# ---- FVG ----

def test_fvg_bull_gap():
    bars = [
        _bar(99, 100, 98, 99, 10),     # high=100
        _bar(101, 108, 101, 107, 20),  # displacement
        _bar(106, 107, 105, 106, 30),  # low=105 → gap 100..105
    ]
    fvgs = find_fair_value_gaps(bars)
    assert len(fvgs) == 1
    z = fvgs[0]
    assert z["type"] == "bull" and z["bottom"] == 100 and z["top"] == 105 and z["index"] == 1


def test_fvg_bear_gap():
    bars = [
        _bar(108, 109, 105, 106, 10),  # low=105
        _bar(104, 104, 96, 97, 20),
        _bar(99, 100, 98, 99, 30),     # high=100 → bear gap 100..105
    ]
    fvgs = find_fair_value_gaps(bars)
    assert fvgs and fvgs[0]["type"] == "bear"
    assert fvgs[0]["top"] == 105 and fvgs[0]["bottom"] == 100


def test_fvg_none_when_no_gap():
    bars = [_bar(100, 102, 99, 101, t) for t in range(3)]
    assert find_fair_value_gaps(bars) == []


# ---- Order Block ----

def test_order_block_bull():
    bars = [
        _bar(100, 100, 98, 99, 10),    # kırmızı mum (OB adayı), high=100 low=98
        _bar(99, 103, 99, 102, 20),    # yeşil, close 102 > 100 → kırılım
        _bar(102, 106, 101, 105, 30),  # yeşil
        _bar(105, 107, 104, 106, 40),
    ]
    obs = find_order_blocks(bars, displacement=3)
    assert any(o["type"] == "bull" and o["top"] == 100 and o["bottom"] == 98
               and o["index"] == 0 for o in obs)


def test_order_block_none_when_no_displacement():
    # Kırmızı mum sonrası high kırılmıyor → OB yok
    bars = [
        _bar(100, 100, 98, 99, 10),
        _bar(99, 99.5, 98, 99, 20),
        _bar(99, 99.8, 98, 99, 30),
        _bar(99, 99.9, 98, 99, 40),
    ]
    assert find_order_blocks(bars, displacement=3) == []


# ---- Liquidity Sweep ----

def test_liquidity_sweep_bull_true():
    bars = [
        _bar(105, 106, 100, 104, 10),  # old_low = 100
        _bar(104, 105, 101, 103, 20),
        _bar(103, 104, 98, 102, 30),   # D barı: low 98 < 100, close 102 > 100 → sweep
    ]
    assert check_liquidity_sweep(bars, 2, "bull", lookback=50) is True


def test_liquidity_sweep_bull_false_when_close_below():
    bars = [
        _bar(105, 106, 100, 104, 10),  # old_low = 100
        _bar(104, 105, 101, 103, 20),
        _bar(103, 104, 98, 99, 30),    # close 99 < 100 → gerçek kırılım, sweep değil
    ]
    assert check_liquidity_sweep(bars, 2, "bull", lookback=50) is False


def test_liquidity_sweep_bear_true():
    bars = [
        _bar(95, 100, 94, 96, 10),     # old_high = 100
        _bar(96, 99, 95, 97, 20),
        _bar(97, 102, 96, 98, 30),     # high 102 > 100, close 98 < 100 → bear sweep
    ]
    assert check_liquidity_sweep(bars, 2, "bear", lookback=50) is True


# ---- compute_smc (entegrasyon) ----

class _P:
    def __init__(self, time, price):
        self.time = time
        self.price = price


class _S:
    def __init__(self, direction, d_time, d_price):
        self.direction = direction
        self.pivots = {"D": _P(d_time, d_price)}


def test_compute_smc_fvg_hit():
    # D fiyatı (102) D'den önce oluşmuş bir bull FVG'nin (100..105) içinde.
    bars = [
        _bar(99, 99, 98, 98, 10),
        _bar(100, 100, 99, 99, 20),    # high=100
        _bar(103, 108, 103, 107, 30),  # displacement
        _bar(106, 107, 105, 106, 40),  # low=105 → bull FVG 100..105 (index 2)
        _bar(104, 104, 103, 103, 50),
        _bar(103, 103, 102, 102, 60),
        _bar(102, 103, 101, 102, 70),  # D barı
    ]
    s = _S("bull", d_time=70, d_price=102)
    r = compute_smc(s, bars)
    assert r.fvg is True
    assert r.components["fvg"] == 30.0
    assert r.score >= 30


def test_compute_smc_no_hit_is_zero():
    bars = [_bar(100, 101, 99, 100, t * 10) for t in range(6)]
    s = _S("bull", d_time=50, d_price=100)
    r = compute_smc(s, bars)
    assert r.score == 0
    assert not (r.fvg or r.order_block or r.sweep)


# ---- sweep raporu ----

def _trade(smc: int, t: int) -> dict:
    return {"symbol": f"S{t}", "interval": "60m", "pattern": "X", "direction": "bull",
            "ideal_entry": 100.0, "stop": 99.0, "tp1": 103.0, "fill": 100.0,
            "open_time": t, "close_time": t + 3_600_000, "outcome": "TP", "smc": smc}


def test_smc_sweep_filters():
    trades = [_trade(s, i) for i, s in enumerate([0, 30, 60, 100])]
    out = format_smc_sweep(trades, thresholds=(0, 60))
    assert "SMC" in out
    assert simulate_portfolio([t for t in trades if t["smc"] >= 60]).n_trades == 2
    assert simulate_portfolio(trades).n_trades == 4
