"""ZigZag pivot dedektörü testleri."""
from __future__ import annotations

import pytest

from terminal.detection.pivots import find_pivots
from tests.synthetic import gartley_bull, make_xabcd_klines


def test_empty_or_single_returns_no_pivots():
    assert find_pivots([], 0.02) == []
    one = [{"open_time": 0, "high": 1, "low": 1, "close": 1, "open": 1, "volume": 0}]
    assert find_pivots(one, 0.02) == []


def test_no_movement_below_threshold():
    # 100'den çok küçük dalgalanma → pivot yok
    klines = []
    for i in range(20):
        klines.append({"open_time": i, "open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 0})
    pivots = find_pivots(klines, threshold=0.05)  # %5 eşik
    # Belki ilk pivot bile yok (move < 0.5)
    assert all(p.index in (0, 19) for p in pivots) or pivots == []


def test_detects_synthetic_gartley_5_pivots():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=10)
    pivots = find_pivots(klines, threshold=0.01)
    # ZigZag tam 5 pivot bulmalı (X, A, B, C, D)
    assert len(pivots) == 5
    assert [p.kind for p in pivots] == ["low", "high", "low", "high", "low"]
    # fiyatlar yaklaşık eşleşmeli
    for got, expected in zip(pivots, prices):
        assert abs(got.price - expected) < 0.5, f"pivot {got.price} ≠ beklenen {expected}"


def test_pivots_chronological_order():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=10)
    pivots = find_pivots(klines, threshold=0.01)
    times = [p.time for p in pivots]
    assert times == sorted(times)
