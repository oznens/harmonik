"""XABCD formasyon eşleştirici testleri.

Sentetik (ideal) pivotlardan oluşturulan 5'lileri matcher'a verir,
beklenen formasyon adının ve oran ölçümlerinin doğruluğunu kontrol eder.
"""
from __future__ import annotations

import pytest

from terminal.detection.matcher import build_quintet, match_xabcd
from terminal.detection.pivots import Pivot
from tests.synthetic import (
    bat_bull,
    butterfly_bull,
    crab_bull,
    deep_crab_bull,
    gartley_bull,
    to_bear,
)


def _pivots_from(prices, kinds, base_time=1_700_000_000_000, step_ms=10 * 60_000):
    return [
        Pivot(index=i, time=base_time + i * step_ms, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_build_quintet_bull_valid():
    prices, kinds = gartley_bull()
    p5 = _pivots_from(prices, kinds)
    q = build_quintet(p5)
    assert q is not None
    assert q.direction == "bull"


def test_build_quintet_bear_valid():
    prices, kinds = to_bear(*gartley_bull())
    p5 = _pivots_from(prices, kinds)
    q = build_quintet(p5)
    assert q is not None
    assert q.direction == "bear"


def test_build_quintet_invalid_geometry():
    # B noktası A'nın üstünde — bull geçersiz
    bad = [
        Pivot(0, 1000, 100, "low"),
        Pivot(1, 2000, 120, "high"),
        Pivot(2, 3000, 130, "low"),  # B > A → geçersiz
        Pivot(3, 4000, 125, "high"),
        Pivot(4, 5000, 110, "low"),
    ]
    assert build_quintet(bad) is None


def test_build_quintet_non_alternating_kinds():
    # 2 ardışık high — dönüşümlü değil, reddedilmeli
    bad = [
        Pivot(0, 1000, 100, "low"),
        Pivot(1, 2000, 120, "high"),
        Pivot(2, 3000, 110, "high"),  # high yine
        Pivot(3, 4000, 115, "low"),
        Pivot(4, 5000, 105, "high"),
    ]
    assert build_quintet(bad) is None


def test_matches_ideal_gartley_bull():
    prices, kinds = gartley_bull()
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    assert m.spec.name == "Gartley"
    assert m.quintet.direction == "bull"
    assert abs(m.b_ratio - 0.618) < 0.005
    assert abs(m.d_ratio - 0.786) < 0.005


def test_matches_ideal_gartley_bear():
    prices, kinds = to_bear(*gartley_bull())
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    assert m.spec.name == "Gartley"
    assert m.quintet.direction == "bear"
    assert abs(m.b_ratio - 0.618) < 0.005
    assert abs(m.d_ratio - 0.786) < 0.005


def test_matches_ideal_bat_bull():
    prices, kinds = bat_bull()
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    assert m.spec.name == "Bat"
    assert abs(m.b_ratio - 0.50) < 0.005
    assert abs(m.d_ratio - 0.886) < 0.005


def test_matches_ideal_butterfly_bull():
    prices, kinds = butterfly_bull()
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    assert m.spec.name == "Butterfly"
    assert abs(m.b_ratio - 0.786) < 0.005
    assert abs(m.d_ratio - 1.27) < 0.005


def test_matches_ideal_crab_bull():
    prices, kinds = crab_bull()
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    assert m.spec.name == "Crab"
    assert abs(m.d_ratio - 1.618) < 0.005


def test_matches_ideal_deep_crab_bull():
    prices, kinds = deep_crab_bull()
    m = match_xabcd(_pivots_from(prices, kinds))
    assert m is not None
    # Deep Crab veya Crab (B=0.886 her ikisinin bandına girer mi?
    # Crab b_max=0.668 → B=0.886 Crab'a uymaz. Sadece Deep Crab kalır.
    assert m.spec.name == "Deep Crab"
    assert abs(m.b_ratio - 0.886) < 0.005


def test_no_match_for_random_geometry():
    # B=0.5 ama D=0.5 — hiçbir formasyona uymaz
    p5 = [
        Pivot(0, 0, 100, "low"),
        Pivot(1, 1, 120, "high"),
        Pivot(2, 2, 110, "low"),       # B=0.5 (50% retr)
        Pivot(3, 3, 115, "high"),      # C=0.5 of AB
        Pivot(4, 4, 110, "low"),       # D=0.5 XA — Bat band'ı [0.856, 0.916]'a düşmez
    ]
    assert match_xabcd(p5) is None
