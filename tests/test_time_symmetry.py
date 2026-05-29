"""Zaman simetrisi (#2 yapısal filtre): AB/CD süre oranı + portföy sweep."""
from __future__ import annotations

from terminal.detection.scanner import time_symmetry
from terminal.karakter.portfolio import format_symmetry_sweep, simulate_portfolio


class _P:
    def __init__(self, t: int):
        self.time = t


class _S:
    def __init__(self, times: dict):
        self.pivots = {k: _P(v) for k, v in times.items()}


def test_time_symmetry_equal_legs_is_one():
    # AB = 100, CD = 100 → tam simetrik
    s = _S({"X": 0, "A": 100, "B": 200, "C": 300, "D": 400})
    assert time_symmetry(s) == 1.0


def test_time_symmetry_asymmetric():
    # AB = 100, CD = 400 → 0.25
    s = _S({"X": 0, "A": 100, "B": 200, "C": 300, "D": 700})
    assert abs(time_symmetry(s) - 0.25) < 1e-9


def test_time_symmetry_zero_leg():
    s = _S({"X": 0, "A": 100, "B": 100, "C": 300, "D": 400})  # AB=0
    assert time_symmetry(s) == 0.0


def _trade(sym: float, t: int) -> dict:
    return {"symbol": f"S{t}", "interval": "60m", "pattern": "X", "direction": "bull",
            "ideal_entry": 100.0, "stop": 99.0, "tp1": 103.0, "fill": 100.0,
            "open_time": t, "close_time": t + 3_600_000, "outcome": "TP", "symmetry": sym}


def test_symmetry_sweep_filters():
    trades = [_trade(s, i) for i, s in enumerate([0.1, 0.4, 0.6, 0.9])]
    out = format_symmetry_sweep(trades, thresholds=(0.0, 0.5))
    assert "SİMETRİ" in out
    # >=0.0 → 4 işlem, >=0.5 → 2 (0.6, 0.9)
    assert simulate_portfolio([t for t in trades if t["symmetry"] >= 0.5]).n_trades == 2
    assert simulate_portfolio(trades).n_trades == 4
