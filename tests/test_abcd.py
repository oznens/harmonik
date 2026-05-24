"""AB=CD pattern matcher testleri."""
from __future__ import annotations

from terminal.detection.patterns.abcd import (
    AB_CD_RATIOS,
    AB_CD_TOLERANCE,
    build_abcd_setup,
    match_abcd,
)
from terminal.detection.pivots import Pivot


def _pivots(prices: list[float], kinds: list[str]) -> list[Pivot]:
    return [
        Pivot(index=i, time=1_700_000_000_000 + i * 60_000, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_bull_abcd_equivalent():
    # A=120 high, B=100 low, C=112 high (60% retracement), D=92 low (CD=AB)
    p = _pivots([120, 100, 112, 92], ["high", "low", "high", "low"])
    m = match_abcd(p)
    assert m is not None
    assert m.direction == "bull"
    assert abs(m.cd_ab_ratio - 1.0) < 0.01
    assert m.matched_ratio == 1.0
    assert 0.382 <= m.c_ratio <= 0.886


def test_bear_abcd_equivalent():
    # A=80 low, B=100 high, C=88 low, D=108 high (CD=AB)
    p = _pivots([80, 100, 88, 108], ["low", "high", "low", "high"])
    m = match_abcd(p)
    assert m is not None
    assert m.direction == "bear"
    assert abs(m.cd_ab_ratio - 1.0) < 0.01


def test_bull_127_abcd():
    # A=120, B=100, C=112, D = C - 1.27 * AB = 112 - 25.4 = 86.6
    p = _pivots([120, 100, 112, 86.6], ["high", "low", "high", "low"])
    m = match_abcd(p)
    assert m is not None
    assert m.matched_ratio == 1.27
    assert m.pattern_name == "1.27 AB=CD"


def test_bull_1618_abcd():
    # A=120, B=100, C=112, D = C - 1.618 * AB = 112 - 32.36 = 79.64
    p = _pivots([120, 100, 112, 79.64], ["high", "low", "high", "low"])
    m = match_abcd(p)
    assert m is not None
    assert m.matched_ratio == 1.618


def test_invalid_c_outside_ab_range():
    # C is BELOW B (not retracement of AB)
    p = _pivots([120, 100, 95, 80], ["high", "low", "high", "low"])
    m = match_abcd(p)
    assert m is None


def test_invalid_cd_not_standard_ratio():
    # CD/AB = 0.7 (none of standard ratios)
    p = _pivots([120, 100, 112, 98], ["high", "low", "high", "low"])
    m = match_abcd(p)
    assert m is None  # CD = 14, AB = 20, ratio = 0.7 — not in {1.0, 1.13, 1.27, ...}


def test_non_alternating_rejected():
    p = _pivots([120, 100, 95, 92], ["high", "low", "low", "low"])
    m = match_abcd(p)
    assert m is None


def test_three_pivots_rejected():
    p = _pivots([120, 100, 110], ["high", "low", "high"])
    m = match_abcd(p)
    assert m is None


# ---- Setup build ----

def test_build_setup_bull():
    p = _pivots([120, 100, 112, 92], ["high", "low", "high", "low"])
    m = match_abcd(p)
    s = build_abcd_setup(m, "TEST", "60m")
    assert s.symbol == "TEST"
    assert s.pattern_family == "abcd"
    assert s.direction == "bull"
    assert s.ab_cd_equivalent is True
    # Entry ~ D level
    assert abs(s.entry - 92) < 1.0
    # TP1 should be above entry (bull)
    assert s.tp1 > s.entry
    # SL should be below entry
    assert s.stop < s.entry
    # X is duplicated from A
    assert s.pivots["X"].time == s.pivots["A"].time


def test_build_setup_bear():
    p = _pivots([80, 100, 88, 108], ["low", "high", "low", "high"])
    m = match_abcd(p)
    s = build_abcd_setup(m, "TEST", "60m")
    assert s.direction == "bear"
    # TP1 should be below entry (bear)
    assert s.tp1 < s.entry
    # SL should be above entry
    assert s.stop > s.entry
