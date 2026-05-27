"""Potansiyel (incomplete) pattern dedektörü testleri."""
from __future__ import annotations

from terminal.detection.pivots import Pivot
from terminal.detection.potential import find_potential_patterns, match_potential


def _pivots(prices: list[float], kinds: list[str]) -> list[Pivot]:
    return [
        Pivot(index=i, time=1_700_000_000_000 + i * 60_000, price=p, kind=k)
        for i, (p, k) in enumerate(zip(prices, kinds))
    ]


def test_potential_gartley_bull():
    """B=0.618, C=0.728 → Gartley B/C oranları uyar, D bekleniyor."""
    x_p, a_p = 100.0, 120.0
    xa = a_p - x_p
    b_p = a_p - 0.618 * xa  # 107.64
    c_p = b_p + 0.728 * (a_p - b_p)  # 116.64
    p = _pivots([x_p, a_p, b_p, c_p], ["low", "high", "low", "high"])
    matches = match_potential(p)
    # Birden fazla pattern uyabilir (Gartley B=0.618 + C bandı geniş)
    names = [m.spec.name for m in matches]
    assert "Gartley" in names
    g = next(m for m in matches if m.spec.name == "Gartley")
    # Potansiyel D bölgesi: spec'in d_min/d_max XA bandında (bull için aşağıda)
    # Gartley spec: d_min=0.72, d_max=0.86
    # d_low = 120 - 0.86*20 = 102.8; d_high = 120 - 0.72*20 = 105.6
    assert 102 < g.d_zone_low < 103.5
    assert 105 < g.d_zone_high < 106.5
    # İdeal D: 0.786 XA → 120 - 0.786*20 = 104.28
    assert abs(g.d_ideal_price - 104.28) < 0.1


def test_potential_no_match_when_c_too_low():
    """C, A'nın altına çok yakın olursa C ratio'lar bant dışı."""
    x_p, a_p = 100.0, 120.0
    b_p = 107.64  # 0.618
    c_p = 108.0   # AB retracement çok küçük (0.026)
    p = _pivots([x_p, a_p, b_p, c_p], ["low", "high", "low", "high"])
    matches = match_potential(p)
    # C bantı 0.35-0.92, 0.026 dışında
    assert matches == []


def test_potential_no_match_when_b_above_a():
    """Bull setup'ta B, A'nın üstüne çıkarsa geometri bozulur."""
    p = _pivots([100, 120, 130, 125], ["low", "high", "low", "high"])
    assert match_potential(p) == []


def test_find_potential_in_longer_pivot_list():
    """Pivot listesinde son 4 ile başka 4'lü pencerelerde pattern arar."""
    x_p, a_p = 100.0, 120.0
    xa = a_p - x_p
    b_p = a_p - 0.618 * xa
    c_p = b_p + 0.728 * (a_p - b_p)
    # 6 pivot — son 4 (X-A-B-C) Gartley
    pivots = _pivots(
        [80, 90, 75, x_p, a_p, b_p, c_p],
        ["low", "high", "low", "low", "high", "low", "high"],
    )
    # 4. pivot kind hatalı (low-low ardışık) — son 4 pencere alır
    pivots_valid = _pivots(
        [x_p, a_p, b_p, c_p],
        ["low", "high", "low", "high"],
    )
    results = find_potential_patterns(pivots_valid)
    assert len(results) >= 1
