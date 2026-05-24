"""Shark pattern matcher testleri."""
from __future__ import annotations

from terminal.detection.patterns.shark import build_shark_setup, match_shark
from terminal.detection.pivots import Pivot


def _pivots(prices: list[float], kinds: list[str]) -> list[Pivot]:
    return [
        Pivot(index=i, time=1_700_000_000_000 + i * 60_000, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_bull_shark_valid():
    # Bull Shark: 0(L)=80, X(H)=100, A(L)=92, B(H)=110, C(L)=80
    # 0X = 20 up
    # A retr of 0X = (100-92)/20 = 0.40 ✓ in [0.382, 0.618]
    # XA = 8; B - A = 18; B ext XA = 18/8 = 2.25 ❌ (>1.618)
    # Need B closer: let me recompute
    # A=92, XA=8. B ext 1.5 → B = A + 1.5*8 = 92+12 = 104. (B above X)
    # AB = 104-92 = 12. C ext AB 1.8 → C = B - 1.8*12 = 104-21.6 = 82.4
    # 0B = 104-80 = 24. C retr 0B = (104-82.4)/24 = 21.6/24 = 0.9 ✓ in [0.886, 1.13]
    p = _pivots([80, 100, 92, 104, 82.4], ["low", "high", "low", "high", "low"])
    m = match_shark(p)
    assert m is not None
    assert m.direction == "bull"
    assert 0.382 <= m.a_retr_0x <= 0.618
    assert 1.13 <= m.b_ext_xa <= 1.618
    assert 1.618 <= m.c_ext_ab <= 2.24
    assert 0.886 <= m.c_retr_0b <= 1.13


def test_bear_shark_valid():
    # Bear Shark: mirror of bull
    # 0(H)=120, X(L)=100, A(H)=108, B(L)=96, C(H)=117.6
    p = _pivots([120, 100, 108, 96, 117.6], ["high", "low", "high", "low", "high"])
    m = match_shark(p)
    assert m is not None
    assert m.direction == "bear"


def test_invalid_a_outside_retr():
    # A çok düşük (0X retr < 0.382)
    p = _pivots([80, 100, 85, 104, 82.4], ["low", "high", "low", "high", "low"])
    m = match_shark(p)
    assert m is None


def test_invalid_b_not_above_x():
    # B X'in üstünde değil
    p = _pivots([80, 100, 92, 98, 82.4], ["low", "high", "low", "high", "low"])
    m = match_shark(p)
    assert m is None


def test_invalid_c_not_below_0():
    # C 0'ın altında değil
    p = _pivots([80, 100, 92, 104, 85], ["low", "high", "low", "high", "low"])
    m = match_shark(p)
    assert m is None  # C=85, 0=80, C > 0 → invalid


def test_non_alternating():
    p = _pivots([80, 100, 95, 90, 80], ["low", "high", "low", "low", "low"])
    m = match_shark(p)
    assert m is None


def test_build_setup_bull():
    p = _pivots([80, 100, 92, 104, 82.4], ["low", "high", "low", "high", "low"])
    m = match_shark(p)
    s = build_shark_setup(m, "TEST", "60m")
    assert s.pattern_family == "shark"
    assert s.pattern_name == "Shark"
    assert s.direction == "bull"
    # Entry = C level (82.4)
    assert abs(s.entry - 82.4) < 0.1
    # SL below entry (bull)
    assert s.stop < s.entry
    # TP1 above entry (bull, dönüş yukarı)
    assert s.tp1 > s.entry
    # Pivot mapping: X=0, A=X, B=A, C=B, D=C
    assert s.pivots["X"].price == 80
    assert s.pivots["A"].price == 100
    assert s.pivots["D"].price == 82.4


def test_build_setup_bear():
    p = _pivots([120, 100, 108, 96, 117.6], ["high", "low", "high", "low", "high"])
    m = match_shark(p)
    s = build_shark_setup(m, "TEST", "60m")
    assert s.direction == "bear"
    assert s.tp1 < s.entry  # bear, hedef aşağı
    assert s.stop > s.entry  # bear SL yukarıda
