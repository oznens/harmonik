"""Three Drives formasyonu (Carney The Harmonic Trader 1999).

Noktalar: 5 pivot — 3 itiş (drive_1, drive_2, drive_3) + 2 düzeltme (retr_1, retr_2).
notlar/08-three-drives.md:
  - İtişler arası düzeltme: önceki itişin retracement'i (~0.618 veya 0.786)
  - Her itiş: önceki düzeltmenin projeksiyonu (~1.27 veya 1.618)
  - Zaman simetrisi: itişler arası bar sayısı yakın olmalı
  - Asıl belirleyici: simetri (fiyat + zaman)
  - Oranlar kesin olmak zorunda değil — Carney "yakın" der

Pivot yapısı (alternating):
  Bull (dipte 3 düşüş):  d1(H), r1(L), d2(H), r2(L), d3(H) → WAIT bu bear
  Bull (dipte alış):     d1(L), r1(H), d2(L), r2(H), d3(L) → 3 lower low
  Bear (tepede satış):   d1(H), r1(L), d2(H), r2(L), d3(H) → 3 higher high
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot

# Three Drives oran aralıkları (Carney esnek tutar)
RETR_MIN = 0.50      # düzeltme oran min (0.618-0.786 tercih ama esnek)
RETR_MAX = 0.886
DRIVE_PROJ_MIN = 1.13
DRIVE_PROJ_MAX = 1.80
# Simetri toleransı (zaman): itişler arası bar sayısı oranı [0.5, 2.0]
TIME_SYM_MIN = 0.5
TIME_SYM_MAX = 2.0


@dataclass
class ThreeDrivesMatchResult:
    direction: str
    d1: Pivot   # drive 1
    r1: Pivot   # retracement 1
    d2: Pivot   # drive 2 (further than d1)
    r2: Pivot   # retracement 2
    d3: Pivot   # drive 3 (further than d2)
    retr1_ratio: float    # r1'in d1 itişine retracement oranı
    retr2_ratio: float    # r2'nin d2 itişine retracement oranı
    drive2_proj: float    # d2'nin r1-d1 projeksiyonu
    drive3_proj: float    # d3'ün r2-d2 projeksiyonu
    time_symmetry: float  # d2→d3 / d1→d2 bar oranı


def _is_alternating(pivots: list[Pivot]) -> bool:
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def match_three_drives(p5: list[Pivot], interval_ms: int = 3_600_000) -> ThreeDrivesMatchResult | None:
    """5 ardışık pivot Three Drives formasyonuna uyuyor mu?"""
    if len(p5) != 5 or not _is_alternating(p5):
        return None
    d1, r1, d2, r2, d3 = p5

    if d1.kind == "low":
        # Bull Three Drives: 3 lower lows → dipte alış
        direction = "bull"
        # Her drive bir öncekinden DAHA DÜŞÜK
        if not (d2.price < d1.price and d3.price < d2.price):
            return None
        # Düzeltmeler drive'lar arası HIGH
        if not (r1.price > d1.price and r1.price > d2.price):
            return None
        if not (r2.price > d2.price and r2.price > d3.price):
            return None
        # Retracement oranları (düzeltme önceki drive'ın yüzde kaçı)
        d1_d2_dist = d1.price - d2.price  # drive 1→2 düşüş
        retr1 = (r1.price - d2.price) / d1_d2_dist if d1_d2_dist > 0 else 0
        d2_d3_dist = d2.price - d3.price
        retr2 = (r2.price - d3.price) / d2_d3_dist if d2_d3_dist > 0 else 0
        # Drive projeksiyonları (drive bir önceki düzeltmenin uzantısı)
        retr1_dist = r1.price - d2.price  # r1 to d2 retracement size
        drive2_proj = d1_d2_dist / retr1_dist if retr1_dist > 0 else 0
        retr2_dist = r2.price - d3.price
        drive3_proj = d2_d3_dist / retr2_dist if retr2_dist > 0 else 0
    else:
        # Bear Three Drives: 3 higher highs → tepede satış
        direction = "bear"
        if not (d2.price > d1.price and d3.price > d2.price):
            return None
        if not (r1.price < d1.price and r1.price < d2.price):
            return None
        if not (r2.price < d2.price and r2.price < d3.price):
            return None
        d1_d2_dist = d2.price - d1.price
        retr1 = (d2.price - r1.price) / d1_d2_dist if d1_d2_dist > 0 else 0
        d2_d3_dist = d3.price - d2.price
        retr2 = (d3.price - r2.price) / d2_d3_dist if d2_d3_dist > 0 else 0
        retr1_dist = d2.price - r1.price
        drive2_proj = d1_d2_dist / retr1_dist if retr1_dist > 0 else 0
        retr2_dist = d3.price - r2.price
        drive3_proj = d2_d3_dist / retr2_dist if retr2_dist > 0 else 0

    # Oran kontrolleri
    if not (RETR_MIN <= retr1 <= RETR_MAX):
        return None
    if not (RETR_MIN <= retr2 <= RETR_MAX):
        return None
    if not (DRIVE_PROJ_MIN <= drive2_proj <= DRIVE_PROJ_MAX):
        return None
    if not (DRIVE_PROJ_MIN <= drive3_proj <= DRIVE_PROJ_MAX):
        return None

    # Zaman simetrisi: d2→d3 / d1→d2 bar sayısı
    bars_d1_d2 = max(1, (d2.time - d1.time) // interval_ms)
    bars_d2_d3 = max(1, (d3.time - d2.time) // interval_ms)
    time_sym = bars_d2_d3 / bars_d1_d2
    if not (TIME_SYM_MIN <= time_sym <= TIME_SYM_MAX):
        return None

    return ThreeDrivesMatchResult(
        direction=direction,
        d1=d1, r1=r1, d2=d2, r2=r2, d3=d3,
        retr1_ratio=retr1, retr2_ratio=retr2,
        drive2_proj=drive2_proj, drive3_proj=drive3_proj,
        time_symmetry=time_sym,
    )


def build_three_drives_setup(m: ThreeDrivesMatchResult, symbol: str, interval: str) -> Setup:
    """Three Drives match'ten Setup nesnesi üret."""
    sign = -1 if m.direction == "bull" else 1
    bars_d1_d2 = abs(m.d2.price - m.d1.price)
    bars_d2_d3 = abs(m.d3.price - m.d2.price)

    # PRZ: d3 etrafında dar — fiyat zaten oraya geldi
    entry = m.d3.price

    # SL: d3'ün biraz ötesi (Butterfly mantığı — ekstremde stop)
    sl_buffer = bars_d2_d3 * 0.15
    if m.direction == "bull":
        stop = m.d3.price - sl_buffer
    else:
        stop = m.d3.price + sl_buffer

    # TP: simetri ile r2 ve r1 seviyeleri
    components: list[tuple[str, float]] = [
        ("D3 (entry)", entry),
        ("R2 hedef", m.r2.price),
        ("R1 hedef", m.r1.price),
    ]

    if m.direction == "bull":
        tp1 = m.r2.price       # ilk hedef: son düzeltme high
        tp2 = m.r1.price       # ikinci hedef: orta düzeltme high
    else:
        tp1 = m.r2.price
        tp2 = m.r1.price

    return Setup(
        symbol=symbol, interval=interval,
        pattern_name="Three Drives", direction=m.direction,
        # Pivot mapping: X=d1, A=r1, B=d2, C=r2, D=d3
        pivots={"X": m.d1, "A": m.r1, "B": m.d2, "C": m.r2, "D": m.d3},
        b_ratio=m.retr1_ratio,
        c_ratio=m.retr2_ratio,
        d_ratio=m.drive3_proj,
        bc_proj=m.drive2_proj,
        cd_ab_ratio=0.0,
        ab_cd_equivalent=False,
        prz_low=min(entry, tp1) if m.direction == "bull" else min(stop, entry),
        prz_high=max(entry, tp1) if m.direction == "bear" else max(stop, entry),
        prz_components=components,
        entry=entry, stop=stop, tp1=tp1, tp2=tp2,
        detected_at=int(time.time() * 1000),
        pattern_family="three_drives",
    )
