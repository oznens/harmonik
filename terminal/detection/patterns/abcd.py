"""AB=CD formasyonu — 4 pivot A-B-C-D yapısı.

notlar/01-ab-cd.md'ye göre:
  - C = AB'nin retracement'i (0.382-0.886, 0.618 tercih)
  - CD/AB oranı standart Carney değerlerden biri: 1.0, 1.13, 1.27, 1.414,
    1.618, 2.0, 2.24, 2.618, 3.14, 3.618 (±%10 tolerans)
  - C noktası retracement → BC projection resiprokal eşleşmesi (perfect AB=CD)

Setup nesnesi içinde X pivot'u A'nın duplikatıdır (4-pivot pattern için
Setup yapısını bozmamak adına).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot

# Standart AB=CD oranları (Carney)
AB_CD_RATIOS = (1.0, 1.13, 1.27, 1.414, 1.618, 2.0, 2.24, 2.618, 3.14, 3.618)
AB_CD_TOLERANCE = 0.10

# C noktası AB retracement aralığı (tüm AB=CD'lerde)
C_MIN = 0.382
C_MAX = 0.886

# Reciprocal eşleşmeleri — C retracement → BC projection beklentisi
# (Perfect AB=CD bonus için kullanılır)
C_TO_BC_RECIPROCAL = {
    0.382: (2.24, 2.618),
    0.500: (2.0, 2.0),
    0.618: (1.618, 1.618),
    0.707: (1.41, 1.41),
    0.786: (1.27, 1.27),
    0.886: (1.13, 1.13),
}


@dataclass
class AbcdMatchResult:
    pattern_name: str       # "AB=CD" veya "1.27 AB=CD" / "1.618 AB=CD"
    direction: str          # "bull" or "bear"
    a: Pivot
    b: Pivot
    c: Pivot
    d: Pivot
    c_ratio: float          # C'nin AB retracement oranı
    cd_ab_ratio: float      # CD/AB oranı
    matched_ratio: float    # Eşleşen standart oran (1.0 / 1.27 / 1.618 vs.)
    bc_proj_ratio: float    # BC projeksiyonu (|CD|/|BC|)
    perfect: bool           # Perfect AB=CD mi (resiprokal eşleşme)


def _is_alternating(p4: list[Pivot]) -> bool:
    for i in range(1, len(p4)):
        if p4[i].kind == p4[i - 1].kind:
            return False
    return True


def match_abcd(p4: list[Pivot]) -> AbcdMatchResult | None:
    """4 ardışık pivot AB=CD formasyonuna uyuyor mu?

    Returns:
        AbcdMatchResult eğer eşleşme varsa, None değilse.
    """
    if len(p4) != 4 or not _is_alternating(p4):
        return None
    a, b, c, d = p4

    if a.kind == "high":
        # Bull AB=CD: A(high), B(low), C(high), D(low)
        direction = "bull"
        if not (b.price < a.price
                and b.price < c.price < a.price
                and d.price < c.price):
            return None
    else:
        # Bear AB=CD: A(low), B(high), C(low), D(high)
        direction = "bear"
        if not (b.price > a.price
                and a.price < c.price < b.price
                and d.price > c.price):
            return None

    ab_len = abs(a.price - b.price)
    cd_len = abs(c.price - d.price)
    bc_len = abs(b.price - c.price)
    if ab_len <= 0 or bc_len <= 0:
        return None

    c_ratio = bc_len / ab_len
    if not (C_MIN <= c_ratio <= C_MAX):
        return None

    cd_ab = cd_len / ab_len
    matched = None
    for ratio in AB_CD_RATIOS:
        if abs(cd_ab - ratio) / ratio <= AB_CD_TOLERANCE:
            matched = ratio
            break
    if matched is None:
        return None

    # Perfect AB=CD: C ratio standart bir reciprocal değere yakın mı
    bc_proj = cd_len / bc_len
    perfect = False
    for c_std, (bc_min, bc_max) in C_TO_BC_RECIPROCAL.items():
        if abs(c_ratio - c_std) < 0.03:
            if bc_min * 0.9 <= bc_proj <= bc_max * 1.1:
                perfect = True
            break

    name = "AB=CD" if matched == 1.0 else f"{matched:.3g} AB=CD"
    return AbcdMatchResult(
        pattern_name=name,
        direction=direction,
        a=a, b=b, c=c, d=d,
        c_ratio=c_ratio,
        cd_ab_ratio=cd_ab,
        matched_ratio=matched,
        bc_proj_ratio=bc_proj,
        perfect=perfect,
    )


def build_abcd_setup(m: AbcdMatchResult, symbol: str, interval: str) -> Setup:
    """AB=CD match'ten Setup nesnesi üret.

    Setup.pivots'ta X = A (duplikat — Setup yapısını bozmamak için).
    pattern_family = "abcd" — UI/chart bunu bilerek render eder.
    """
    sign = -1 if m.direction == "bull" else 1
    ab_len = abs(m.a.price - m.b.price)

    # PRZ bileşenleri: Carney'nin standart AB=CD oranları → CD projection seviyeleri
    components: list[tuple[str, float]] = []
    for ratio in (1.0, 1.27, 1.618):
        d_candidate = m.c.price + sign * ratio * ab_len
        label = "AB=CD" if ratio == 1.0 else f"{ratio:.3g} AB=CD"
        components.append((label, d_candidate))
    # BC projection ile D = C + bc_proj * BC ekle
    bc_len = abs(m.b.price - m.c.price)
    for bc_proj in (1.618, 2.0, 2.618):
        d_candidate = m.c.price + sign * bc_proj * bc_len
        # PRZ aralığı içine yakın olanlar görüntülenebilir
        components.append((f"{bc_proj:.3g} BC", d_candidate))

    prices = [p for _, p in components]
    # Actual D yakınındaki bileşenleri PRZ'ye dahil et (en yakın 4 tanesi)
    prices_sorted = sorted(prices, key=lambda p: abs(p - m.d.price))[:5]
    prz_low = min(prices_sorted)
    prz_high = max(prices_sorted)

    # Entry = standart AB=CD projection seviyesi (matched_ratio kullanılır)
    entry = m.c.price + sign * m.matched_ratio * ab_len

    # Stop loss: D'nin %20 CD uzakta (sıkı stop, BTC+ETH 15m optimizasyonu)
    # Test: SL 0.20 + TP=B kombosu mevcut formülün 3x R verir, WR korunur (~%50-65)
    cd_actual = abs(m.c.price - entry)
    sl_buffer = cd_actual * 0.20  # %20 ek buffer (önceden %38.2)
    stop = entry + sign * sl_buffer  # bull: aşağıda; bear: yukarıda

    # TP: AB=CD reversal'ında ilk doğal hedef B seviyesi (önceki swing).
    # TP2 = C seviyesi (tam retracement endpoint). Mevcut 0.382 IPO yerine
    # gerçek swing seviyelerini kullan — testte WR %53→%62.5, Avg R +0.22→+0.38.
    tp1 = m.b.price
    tp2 = m.c.price

    # AB=CD onayı her zaman var (formasyonun kendisi)
    ab_cd_equivalent = True

    return Setup(
        symbol=symbol,
        interval=interval,
        pattern_name=m.pattern_name,
        direction=m.direction,
        # X yerine A'nın kopyasını koy — Setup yapısını bozmamak için
        pivots={"X": m.a, "A": m.a, "B": m.b, "C": m.c, "D": m.d},
        # XABCD'deki B/C/D ratio kavramları AB=CD'de aynı şekilde geçerli değil;
        # mevcut alanları en uygun şekilde doldur
        b_ratio=0.0,  # X olmadığı için XA retracement yok
        c_ratio=m.c_ratio,
        d_ratio=m.matched_ratio,  # D'nin CD/AB oranı
        bc_proj=m.bc_proj_ratio,
        cd_ab_ratio=m.cd_ab_ratio,
        ab_cd_equivalent=ab_cd_equivalent,
        prz_low=prz_low,
        prz_high=prz_high,
        prz_components=components,
        entry=entry,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        detected_at=int(time.time() * 1000),
        pattern_family="abcd",
    )
