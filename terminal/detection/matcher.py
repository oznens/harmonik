"""XABCD 5-pivot kombinasyonundan formasyon eşleştirici.

5 ardışık pivot al, yapısal geometriyi doğrula (bull/bear), her bilinen
formasyon spec'i için oran kontrollerini çalıştır. Birden fazla pattern
uyarsa d_ideal'a en yakın olanı seç.
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.detection.pivots import Pivot
from terminal.detection.ratios import (
    b_retracement_of_xa,
    bc_projection,
    c_retracement_of_ab,
    cd_to_ab_ratio,
    d_ratio_of_xa,
)
from terminal.detection.spec import AB_CD_TOLERANCE, PATTERNS, PatternSpec


@dataclass
class PivotQuintet:
    """5 ardışık pivot + yön."""
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    d: Pivot
    direction: str  # "bull" veya "bear"


def _alternating(pivots: list[Pivot]) -> bool:
    """Pivotlar high/low dönüşümlü mü?"""
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def build_quintet(p5: list[Pivot]) -> PivotQuintet | None:
    """5 pivot için bull/bear yönünü belirle, yapısal geometriyi doğrula."""
    if len(p5) != 5 or not _alternating(p5):
        return None
    x, a, b, c, d = p5

    if x.kind == "low":
        # Bull XABCD: X low, A high, B low, C high, D low
        if not (a.price > x.price
                and x.price < b.price < a.price       # B retracement of XA
                and b.price < c.price < a.price       # C retracement of AB
                and d.price < c.price                  # CD down
                and a.price - b.price > 0):
            return None
        return PivotQuintet(x, a, b, c, d, "bull")

    # x.kind == "high" → bear XABCD
    if not (a.price < x.price
            and a.price < b.price < x.price          # B retracement of XA
            and a.price < c.price < b.price          # C retracement of AB
            and d.price > c.price                     # CD up
            and b.price - a.price > 0):
        return None
    return PivotQuintet(x, a, b, c, d, "bear")


def _ab_cd_match(cd_ab: float, spec: PatternSpec) -> bool:
    """CD/AB oranı spec'in AB=CD hedeflerinden birine yakın mı? (yüzde tolerans)"""
    for target in spec.ab_cd_target_ratios:
        if abs(cd_ab - target) / target <= AB_CD_TOLERANCE:
            return True
    return False


@dataclass
class MatchResult:
    spec: PatternSpec
    quintet: PivotQuintet
    b_ratio: float
    c_ratio: float
    d_ratio: float
    bc_proj: float
    cd_ab_ratio: float
    ab_cd_equivalent: bool


def _check_spec(q: PivotQuintet, spec: PatternSpec) -> MatchResult | None:
    x, a, b, c, d = q.x.price, q.a.price, q.b.price, q.c.price, q.d.price

    b_r = b_retracement_of_xa(x, a, b)
    if not (spec.b_min <= b_r <= spec.b_max):
        return None

    c_r = c_retracement_of_ab(a, b, c)
    if not (spec.c_min <= c_r <= spec.c_max):
        return None

    d_r = d_ratio_of_xa(x, a, d)
    if not (spec.d_min <= d_r <= spec.d_max):
        return None

    bc_p = bc_projection(b, c, d)
    if not (spec.bc_proj_min <= bc_p <= spec.bc_proj_max):
        return None

    cd_ab = cd_to_ab_ratio(a, b, c, d)
    ab_cd_eq = _ab_cd_match(cd_ab, spec)

    return MatchResult(
        spec=spec, quintet=q,
        b_ratio=b_r, c_ratio=c_r, d_ratio=d_r,
        bc_proj=bc_p, cd_ab_ratio=cd_ab,
        ab_cd_equivalent=ab_cd_eq,
    )


def match_xabcd(p5: list[Pivot]) -> MatchResult | None:
    """5 pivot için en iyi eşleşen pattern'i döner (d_ideal'a en yakın)."""
    q = build_quintet(p5)
    if q is None:
        return None

    best: MatchResult | None = None
    best_distance = float("inf")
    for spec in PATTERNS.values():
        m = _check_spec(q, spec)
        if m is None:
            continue
        # Tie-breaker: d_ideal'a en yakın olan
        distance = abs(m.d_ratio - spec.d_ideal)
        if distance < best_distance:
            best_distance = distance
            best = m
    return best
