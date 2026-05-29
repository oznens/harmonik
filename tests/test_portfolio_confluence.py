"""Portföy backtest'te confluence filtresi + eşik taraması (canlı paper ile aynı)."""
from __future__ import annotations

from terminal.karakter.portfolio import format_confluence_sweep, simulate_portfolio


def _trade(sym: str, conf: int, outcome: str, t: int) -> dict:
    return {
        "symbol": sym, "interval": "60m", "pattern": "X", "direction": "bull",
        "ideal_entry": 100.0, "stop": 99.0, "tp1": 103.0, "fill": 100.0,
        "open_time": t, "close_time": t + 3_600_000, "outcome": outcome,
        "confluence": conf,
    }


def test_min_confluence_filters_portfolio():
    trades = [
        _trade("AAA", 40, "STOP", 1_000),   # düşük conf → eşik üstünde elenmeli
        _trade("BBB", 60, "TP", 2_000),     # yüksek conf
    ]
    assert simulate_portfolio(trades, min_confluence=0).n_trades == 2
    r50 = simulate_portfolio(trades, min_confluence=50)
    assert r50.n_trades == 1 and r50.tp == 1 and r50.stop == 0


def test_confluence_sweep_table():
    trades = [_trade(f"S{i}", c, "TP", 1_000 + i)
              for i, c in enumerate([10, 40, 55, 80])]
    out = format_confluence_sweep(trades, thresholds=(0, 50, 70))
    assert "TARAMASI" in out
    for th in (">=0", ">=50", ">=70"):
        assert th in out
    # >=0 hepsi (4), >=50 ikisi (55,80), >=70 biri (80)
    assert simulate_portfolio(trades, min_confluence=0).n_trades == 4
    assert simulate_portfolio(trades, min_confluence=50).n_trades == 2
    assert simulate_portfolio(trades, min_confluence=70).n_trades == 1
