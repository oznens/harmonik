"""Carney Vol.3 değerlerine göre XABCD formasyon parametreleri.

Tüm oranlar XA bacağına göredir (B retracement, D retracement/extension).
C için AB bacağına göre retracement. BC projection için CD/BC.
Toleranslar bandın min/max'ına dahil edilmiştir.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatternSpec:
    name: str

    # B noktası: XA retracement bandı
    b_min: float
    b_max: float

    # C noktası: AB retracement bandı (genelde 0.382-0.886, hepsinde aynı)
    c_min: float
    c_max: float

    # D noktası: XA değeri (retracement <1 veya extension >1)
    d_min: float
    d_max: float
    d_ideal: float

    # BC projeksiyonu (|CD|/|BC|) bandı
    bc_proj_min: float
    bc_proj_max: float

    # AB=CD onayı için kabul edilen CD/AB oran(lar)ı — biri D ile çakışırsa onay var
    ab_cd_target_ratios: tuple[float, ...]

    # Stop loss seviyesi (XA cinsi, D'nin ötesinde)
    stop_at_xa: float


# C noktası tüm formasyonlarda 0.382-0.886 AB retracement aralığında
_C_MIN = 0.382
_C_MAX = 0.886

# AB=CD onayı için CD oranının hedefe yaklaşıklık toleransı (yüzde)
AB_CD_TOLERANCE = 0.10


PATTERNS: dict[str, PatternSpec] = {
    # Gartley — 0.618 B, 0.786 D. PDF: yaklaşık değerler kabul (±5pp tolerans).
    "Gartley": PatternSpec(
        name="Gartley",
        b_min=0.568, b_max=0.668,
        c_min=_C_MIN, c_max=_C_MAX,
        d_min=0.736, d_max=0.836, d_ideal=0.786,
        bc_proj_min=1.13, bc_proj_max=1.618,
        ab_cd_target_ratios=(1.0, 1.27),
        stop_at_xa=1.0,
    ),

    # Bat — B<0.618 (0.50 ideal), D=0.886. BC ≥ 1.618 zorunlu. ±5pp D tolerans.
    "Bat": PatternSpec(
        name="Bat",
        b_min=0.382, b_max=0.618,
        c_min=_C_MIN, c_max=_C_MAX,
        d_min=0.836, d_max=0.936, d_ideal=0.886,
        bc_proj_min=1.618, bc_proj_max=2.618,
        ab_cd_target_ratios=(1.0, 1.27),
        stop_at_xa=1.13,
    ),

    # Butterfly — B = 0.786, D = 1.27 extension. PDF: D 1.27-1.618; B ±5pp.
    "Butterfly": PatternSpec(
        name="Butterfly",
        b_min=0.736, b_max=0.836,
        c_min=_C_MIN, c_max=_C_MAX,
        d_min=1.22, d_max=1.618, d_ideal=1.27,
        bc_proj_min=1.618, bc_proj_max=2.618,
        ab_cd_target_ratios=(1.0, 1.27),
        stop_at_xa=1.618,  # PDF: SL 1.618 XA ext ötesi
    ),

    # Crab — B = 0.382-0.618, D = 1.618 extension. PDF: BC 2.24-3.618.
    "Crab": PatternSpec(
        name="Crab",
        b_min=0.332, b_max=0.668,
        c_min=_C_MIN, c_max=_C_MAX,
        d_min=1.568, d_max=1.668, d_ideal=1.618,
        bc_proj_min=2.24, bc_proj_max=3.618,
        ab_cd_target_ratios=(1.0, 1.27, 1.618),
        stop_at_xa=2.0,
    ),
}
# PDF Trading Strategy Guides kapsamında olmayan ve kaldırılan pattern'ler:
# - Alternate Bat (Carney spec; PDF'te yer almıyor)
# - Deep Crab (Carney spec; PDF'te yer almıyor)
# Standalone pattern'ler (PDF kapsamı dışı): AB=CD, 5-0, Three Drives.
