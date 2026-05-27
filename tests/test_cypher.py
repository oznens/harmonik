"""Cypher pattern matcher testleri."""
from __future__ import annotations

from terminal.detection.patterns.cypher import build_cypher_setup, match_cypher
from terminal.detection.pivots import Pivot


def _pivots(prices: list[float], kinds: list[str]) -> list[Pivot]:
    return [
        Pivot(index=i, time=1_700_000_000_000 + i * 60_000, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_bull_cypher_ideal():
    """Bull Cypher: X=100 (low), A=120 (high), B=110 (low, %50 AB retr),
    C=126 (high, %130 XA ext = 100 + 1.30*20), D=109.6 (XC retr 0.786).
    XC = 126 - 100 = 26. D = 126 - 0.786*26 = 105.56.
    """
    x_p = 100.0
    a_p = 120.0
    b_p = a_p - 0.50 * (a_p - x_p)   # 110, %50 AB retr
    c_p = x_p + 1.30 * (a_p - x_p)   # 126, %130 XA ext
    d_p = c_p - 0.786 * (c_p - x_p)  # 105.56, XC %78.6 retr
    p = _pivots([x_p, a_p, b_p, c_p, d_p], ["low", "high", "low", "high", "low"])
    m = match_cypher(p)
    assert m is not None
    assert m.direction == "bull"
    assert 0.382 <= m.ab_retr_xa <= 0.618
    assert 1.272 <= m.c_pos_xa <= 1.414
    assert abs(m.d_retr_xc - 0.786) < 0.05


def test_bear_cypher_ideal():
    x_p = 200.0
    a_p = 180.0
    b_p = a_p + 0.50 * (x_p - a_p)
    c_p = x_p - 1.30 * (x_p - a_p)
    d_p = c_p + 0.786 * (x_p - c_p)
    p = _pivots([x_p, a_p, b_p, c_p, d_p], ["high", "low", "high", "low", "high"])
    m = match_cypher(p)
    assert m is not None
    assert m.direction == "bear"


def test_cypher_c_not_above_a_rejected():
    """C, A'nın üstünde olmazsa Cypher değil (Carney XABCD'ye benzer, Cypher değil)."""
    # C = 0.50 retracement of AB (A ile B arasında, A'nın altında)
    p = _pivots([100, 120, 110, 115, 105], ["low", "high", "low", "high", "low"])
    m = match_cypher(p)
    assert m is None  # C < A → reject


def test_cypher_d_below_x_rejected():
    """D, X'in altına inerse XC retracement>1 olur (geçersiz)."""
    x_p = 100.0
    a_p = 120.0
    b_p = 110.0
    c_p = 126.0  # %130 XA ext
    d_p = 95.0   # X'in altında
    p = _pivots([x_p, a_p, b_p, c_p, d_p], ["low", "high", "low", "high", "low"])
    m = match_cypher(p)
    assert m is None


def test_build_setup_bull():
    x_p, a_p = 100.0, 120.0
    b_p = a_p - 0.50 * (a_p - x_p)
    c_p = x_p + 1.30 * (a_p - x_p)
    d_p = c_p - 0.786 * (c_p - x_p)
    p = _pivots([x_p, a_p, b_p, c_p, d_p], ["low", "high", "low", "high", "low"])
    m = match_cypher(p)
    s = build_cypher_setup(m, "TEST", "60m")
    assert s.pattern_family == "cypher"
    assert s.direction == "bull"
    # Entry D pivot fiyatına eşit (yeni: Carney mantığı)
    assert abs(s.entry - d_p) < 1e-6
    # TP1 = A (XA başlangıç swing)
    assert abs(s.tp1 - a_p) < 1e-6
    # SL D'nin altında (bull)
    assert s.stop < s.entry
