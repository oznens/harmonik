"""Potansiyel (incomplete) XABCD pattern dedektörü.

X-A-B-C 4 pivot oluşmuşsa, her pattern spec'i için potansiyel D bölgesini
hesaplar. Bu, "fiyat henüz D'ye gelmedi ama gelirse Bullish Gartley olur"
tipi öngörü için kullanılır.

TradingView'de manuel olarak çizilen "olası dönüş" pattern'inin otomatik
karşılığı. Trader fiyat D bölgesine girmeden hazırlık yapabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.detection.pivots import Pivot
from terminal.detection.ratios import (
    b_retracement_of_xa,
    c_retracement_of_ab,
)
from terminal.detection.spec import PATTERNS, PatternSpec


@dataclass
class PotentialPattern:
    """Henüz D oluşmamış pattern adayı.

    pivots dict'inde X/A/B/C var, D yok. d_zone_low/high pattern spec'inin
    D bandı XA cinsinden uygulanarak hesaplanır (bull için D = a.price -
    d_ratio * xa_len).
    """
    spec: PatternSpec
    direction: str
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    b_ratio: float
    c_ratio: float
    d_zone_low: float   # potansiyel D'nin min fiyat
    d_zone_high: float  # potansiyel D'nin max fiyat
    d_ideal_price: float


def _is_alternating(pivots: list[Pivot]) -> bool:
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def match_potential(p4: list[Pivot]) -> list[PotentialPattern]:
    """X-A-B-C 4-pivot pencerede potansiyel XABCD pattern'leri bul.

    Returns:
        Eşleşen pattern listesi (B/C oranlarına uyan tüm spec'ler).
    """
    if len(p4) != 4 or not _is_alternating(p4):
        return []
    x, a, b, c = p4

    if x.kind == "low":
        direction = "bull"
        # X(low), A(high), B(low), C(high)
        if not (a.price > x.price and b.price < a.price and b.price >= x.price
                and c.price > b.price and c.price < a.price):
            return []
    else:
        direction = "bear"
        if not (a.price < x.price and b.price > a.price and b.price <= x.price
                and c.price < b.price and c.price > a.price):
            return []

    # Oranlar
    b_r = b_retracement_of_xa(x.price, a.price, b.price)
    c_r = c_retracement_of_ab(a.price, b.price, c.price)
    xa_len = abs(a.price - x.price)
    sign = -1 if direction == "bull" else 1

    matches: list[PotentialPattern] = []
    for spec in PATTERNS.values():
        if not (spec.b_min <= b_r <= spec.b_max):
            continue
        if not (spec.c_min <= c_r <= spec.c_max):
            continue
        # Potansiyel D bölgesi: pattern spec'inin d_min/d_max XA bandı
        d_low = a.price + sign * spec.d_max * xa_len
        d_high = a.price + sign * spec.d_min * xa_len
        if d_low > d_high:
            d_low, d_high = d_high, d_low
        d_ideal = a.price + sign * spec.d_ideal * xa_len
        matches.append(PotentialPattern(
            spec=spec,
            direction=direction,
            x=x, a=a, b=b, c=c,
            b_ratio=b_r, c_ratio=c_r,
            d_zone_low=d_low, d_zone_high=d_high,
            d_ideal_price=d_ideal,
        ))
    return matches


def find_potential_patterns(pivots: list[Pivot]) -> list[PotentialPattern]:
    """Tüm pivot listesinde 4-pivot pencereleri gez, potansiyel pattern'leri çıkar.

    Sadece SON 4-pivot penceresini (en güncel X-A-B-C) döndürmek için
    [-4:] dilim kullanılabilir. Bu fonksiyon tüm pencereleri döner.
    """
    results: list[PotentialPattern] = []
    for i in range(len(pivots) - 3):
        results.extend(match_potential(pivots[i:i + 4]))
    return results
