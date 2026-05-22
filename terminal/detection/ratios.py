"""Harmonik formasyon oran hesaplayıcıları (yön-bağımsız, mutlak değerli)."""
from __future__ import annotations


def b_retracement_of_xa(x: float, a: float, b: float) -> float:
    """B'nin XA bacağına göre retracement oranı. Bull/bear için aynı formül."""
    denom = abs(a - x)
    return abs(a - b) / denom if denom > 0 else 0.0


def c_retracement_of_ab(a: float, b: float, c: float) -> float:
    """C'nin AB bacağına göre retracement oranı (C, B ile A arasında olmalı)."""
    denom = abs(a - b)
    return abs(c - b) / denom if denom > 0 else 0.0


def d_ratio_of_xa(x: float, a: float, d: float) -> float:
    """D'nin XA bacağındaki konumu.

    <1: retracement (D, X ile A arasında).
    =1: D, X seviyesinde.
    >1: extension (D, X'in ötesinde).
    """
    denom = abs(a - x)
    return abs(a - d) / denom if denom > 0 else 0.0


def bc_projection(b: float, c: float, d: float) -> float:
    """CD bacağının BC bacağına oranı (|CD| / |BC|).

    Carney terminolojisinde "BC projection" — BC uzantısının D'yi vurma katı.
    """
    denom = abs(c - b)
    return abs(d - c) / denom if denom > 0 else 0.0


def cd_to_ab_ratio(a: float, b: float, c: float, d: float) -> float:
    """CD/AB. AB=CD onayı için 1.0 (veya pattern'e göre 1.27, 1.618) civarı."""
    denom = abs(a - b)
    return abs(d - c) / denom if denom > 0 else 0.0
