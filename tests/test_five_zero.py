"""5-0 pattern matcher testleri."""
from __future__ import annotations

from terminal.detection.patterns.five_zero import build_five_zero_setup, match_five_zero
from terminal.detection.pivots import Pivot


def _pivots(prices: list[float], kinds: list[str]) -> list[Pivot]:
    return [
        Pivot(index=i, time=1_700_000_000_000 + i * 60_000, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_bull_five_zero_valid():
    # Bull 5-0: X(L)=80, A(H)=100, B(L)=72, C(H)=128, D(L)=100
    # XA = 20 (up); B ext XA = (100-72)/20 = 1.4 ✓ in [1.13, 1.618]
    # AB = 28; C ext AB = (128-72)/28 = 2.0 ✓ in [1.618, 2.24]
    # BC = 56; D retr BC = (128-100)/56 = 0.5 ✓ tanımlayıcı
    # CD = 28 = AB → Reciprocal AB=CD ✓
    p = _pivots([80, 100, 72, 128, 100], ["low", "high", "low", "high", "low"])
    m = match_five_zero(p)
    assert m is not None
    assert m.direction == "bull"
    assert abs(m.d_retr_bc - 0.5) < 0.05
    assert m.abcd_equivalent is True


def test_bear_five_zero_valid():
    # Mirror of bull
    p = _pivots([120, 100, 128, 72, 100], ["high", "low", "high", "low", "high"])
    m = match_five_zero(p)
    assert m is not None
    assert m.direction == "bear"


def test_invalid_b_not_extension():
    # B XA'nın extension'i değil (B X'in üstünde değil ↓ olmalı)
    p = _pivots([80, 100, 92, 128, 100], ["low", "high", "low", "high", "low"])
    m = match_five_zero(p)
    assert m is None


def test_invalid_d_not_50():
    # D %50 retracement değil (örn. %30)
    p = _pivots([80, 100, 72, 128, 112], ["low", "high", "low", "high", "low"])
    m = match_five_zero(p)
    assert m is None  # D retr = 16/56 = 0.286, dışında


def test_invalid_c_not_extension():
    # C AB extension değil
    p = _pivots([80, 100, 72, 90, 80], ["low", "high", "low", "high", "low"])
    m = match_five_zero(p)
    assert m is None


def test_build_setup_bull():
    p = _pivots([80, 100, 72, 128, 100], ["low", "high", "low", "high", "low"])
    m = match_five_zero(p)
    s = build_five_zero_setup(m, "TEST", "60m")
    assert s.pattern_family == "five_zero"
    assert s.pattern_name == "5-0"
    assert s.direction == "bull"
    assert abs(s.entry - 100) < 0.5
    assert s.stop < s.entry
    assert s.tp1 > s.entry
    assert s.ab_cd_equivalent is True
