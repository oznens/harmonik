"""Fraktal (swing yapı + teyit) testleri — tradermiraz 'fraktal' kavramı."""
from __future__ import annotations

from terminal.detection.pivots import Pivot
from terminal.quality.fraktal import (
    fraktal_break_index, fraktal_confirm, fraktal_trend, swing_labels,
)

MS = 3_600_000
T0 = 1_700_000_000_000


def _k(i, c, wick=0.15):
    o = c
    return {"open_time": T0 + i * MS, "close_time": T0 + i * MS + MS - 1,
            "open": o, "high": c + wick, "low": c - wick, "close": c,
            "volume": 100.0, "quote_volume": 1e4}


def _piv(i, price, kind):
    return Pivot(index=i, time=T0 + i * MS, price=price, kind=kind)


def test_swing_labels():
    pivs = [_piv(0, 100, "low"), _piv(2, 120, "high"), _piv(4, 110, "low"),
            _piv(6, 130, "high"), _piv(8, 105, "low")]
    assert [lbl for _, lbl in swing_labels(pivs)] == ["L", "H", "HL", "HH", "LL"]


def test_fraktal_trend_bull_bear_neutral():
    bull = [_piv(0, 100, "low"), _piv(2, 120, "high"), _piv(4, 110, "low"),
            _piv(6, 130, "high")]
    assert fraktal_trend(bull) == "bull"          # HH + HL
    bear = [_piv(0, 120, "high"), _piv(2, 100, "low"), _piv(4, 115, "high"),
            _piv(6, 90, "low")]
    assert fraktal_trend(bear) == "bear"          # LH + LL
    assert fraktal_trend([_piv(0, 100, "low")]) == "neutral"


# Düşüp toparlanan, sonra fraktal üstü/altı kapanan diziler
_BULL = [100, 98, 96, 94, 96, 98, 95, 97, 99, 101]   # son kapanış önceki swing high'ı aşar
_BEAR = [100, 102, 104, 106, 104, 102, 105, 103, 101, 99]


def _series(closes):
    return [_k(i, c) for i, c in enumerate(closes)]


def test_fraktal_confirm_bull():
    assert fraktal_confirm(_series(_BULL), "bull", threshold=0.004) is True


def test_fraktal_confirm_bear():
    assert fraktal_confirm(_series(_BEAR), "bear", threshold=0.004) is True


def test_fraktal_confirm_not_yet():
    # Hâlâ düşen seri — bull teyidi YOK
    falling = _series([100, 99, 98, 97, 96, 95, 94, 93, 92, 91])
    assert fraktal_confirm(falling, "bull", threshold=0.004) is False


def test_fraktal_confirm_min_bars():
    assert fraktal_confirm(_series([100, 101, 102]), "bull", min_bars=8) is False


def test_fraktal_confirm_since_time_filter():
    kl = _series(_BULL)
    # since_time son barların ötesinde → yetersiz bar → False
    assert fraktal_confirm(kl, "bull", since_time=T0 + 9 * MS, threshold=0.004) is False


def test_fraktal_break_index():
    idx = fraktal_break_index(_series(_BULL), "bull", threshold=0.004)
    assert idx is not None and 0 < idx < len(_BULL)
    # düşen seride kırılım yok
    assert fraktal_break_index(_series([100, 99, 98, 97, 96, 95]), "bull",
                               threshold=0.004) is None
