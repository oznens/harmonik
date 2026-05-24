"""5-0 formasyonu (Carney Vol.2/Vol.3).

Noktalar: X, A, B, C, D (D = tamamlanma, entry).
notlar/07-5-0.md kuralları:
  - X-A-B impulsif ters dönüş: B = XA ekstansiyonu 1.13-1.618
  - C = AB ekstansiyonu 1.618-2.24 (en uzun bacak)
  - D = BC bacağının %50 retracement'i (tanımlayıcı limit)
  - D ayrıca Reciprocal AB=CD ile çakışır (PRZ tamamlayıcı)
  - Stop: 0.618 retracement of BC ötesi (ol-ya-da-öl)
  - Entry @ D, TP yapının başlangıcına geri

Pivot yapısı (alternating, 5 pivot):
  Bull 5-0:  X(low),  A(high), B(low),  C(high), D(low)  → D'de long
  Bear 5-0:  X(high), A(low),  B(high), C(low),  D(high) → D'de short

Önemli: B XA'nın UZANTISI → B X'in ÖTESINE geçer (XA'nın yönünde devam).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot

# 5-0 ratio aralıkları (notlar/07-5-0.md, Vol.3)
B_EXT_MIN = 1.13
B_EXT_MAX = 1.618
C_EXT_MIN = 1.618
C_EXT_MAX = 2.24
D_RETR_TARGET = 0.50
D_RETR_TOLERANCE = 0.05   # ±5pp etrafında

# Reciprocal AB=CD onayı için CD/AB tolerance (eşit yakınlık)
AB_CD_TOLERANCE = 0.15


@dataclass
class FiveZeroMatchResult:
    direction: str
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    d: Pivot
    b_ext_xa: float       # B'nin XA extension'i
    c_ext_ab: float       # C'nin AB extension'i
    d_retr_bc: float      # D'nin BC retracement'i (~0.50)
    cd_ab_ratio: float    # Reciprocal AB=CD oranı
    abcd_equivalent: bool # CD ≈ AB (Reciprocal AB=CD onayı)


def _is_alternating(pivots: list[Pivot]) -> bool:
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def match_five_zero(p5: list[Pivot]) -> FiveZeroMatchResult | None:
    """5 ardışık pivot 5-0 formasyonuna uyuyor mu?"""
    if len(p5) != 5 or not _is_alternating(p5):
        return None
    x, a, b, c, d = p5

    if x.kind == "low":
        # Bull 5-0: X(low), A(high), B(low), C(high), D(low)
        direction = "bull"
        # B XA ekstansiyonu (XA up; B downward extension → B below X)
        # C AB ekstansiyonu (AB up; C upward extension → C above A)
        # D BC retracement (BC down — wait, BC up; D retracement down)
        if not (a.price > x.price             # XA up
                and b.price < x.price          # B X'in altında (extension)
                and c.price > a.price          # C A'nın üstünde
                and b.price < d.price < c.price):  # D BC arasında
            return None
        xa_len = a.price - x.price
        b_ext_xa = (a.price - b.price) / xa_len if xa_len > 0 else 0
        ab_len = a.price - b.price
        c_ext_ab = (c.price - b.price) / ab_len if ab_len > 0 else 0
        bc_len = c.price - b.price
        d_retr_bc = (c.price - d.price) / bc_len if bc_len > 0 else 0
        cd_len = c.price - d.price
        cd_ab = cd_len / ab_len if ab_len > 0 else 0
    else:
        # Bear 5-0: X(high), A(low), B(high), C(low), D(high)
        direction = "bear"
        if not (a.price < x.price             # XA down
                and b.price > x.price          # B X'in üstünde
                and c.price < a.price          # C A'nın altında
                and c.price < d.price < b.price):  # D CB arasında
            return None
        xa_len = x.price - a.price
        b_ext_xa = (b.price - a.price) / xa_len if xa_len > 0 else 0
        ab_len = b.price - a.price
        c_ext_ab = (b.price - c.price) / ab_len if ab_len > 0 else 0
        bc_len = b.price - c.price
        d_retr_bc = (d.price - c.price) / bc_len if bc_len > 0 else 0
        cd_len = d.price - c.price
        cd_ab = cd_len / ab_len if ab_len > 0 else 0

    # Oran kontrolleri
    if not (B_EXT_MIN <= b_ext_xa <= B_EXT_MAX):
        return None
    if not (C_EXT_MIN <= c_ext_ab <= C_EXT_MAX):
        return None
    if not (abs(d_retr_bc - D_RETR_TARGET) <= D_RETR_TOLERANCE):
        return None
    # Reciprocal AB=CD onayı (yakınsa bonus, zorunlu değil)
    abcd_eq = abs(cd_ab - 1.0) <= AB_CD_TOLERANCE

    return FiveZeroMatchResult(
        direction=direction,
        x=x, a=a, b=b, c=c, d=d,
        b_ext_xa=b_ext_xa, c_ext_ab=c_ext_ab,
        d_retr_bc=d_retr_bc, cd_ab_ratio=cd_ab,
        abcd_equivalent=abcd_eq,
    )


def build_five_zero_setup(m: FiveZeroMatchResult, symbol: str, interval: str) -> Setup:
    """5-0 match'ten Setup nesnesi üret."""
    sign = -1 if m.direction == "bull" else 1
    bc_len = abs(m.c.price - m.b.price)
    ab_len = abs(m.a.price - m.b.price)

    # PRZ bileşenleri: BC'nin %50 retracement'i ve Reciprocal AB=CD
    components: list[tuple[str, float]] = []
    # %50 retracement of BC (tanımlayıcı)
    d_50 = m.c.price - sign * (-0.5 if m.direction == "bull" else 0.5) * bc_len
    # Düzelttim: bull'da c high, d low (c - 0.5*bc = d); bear'da c low, d high
    if m.direction == "bull":
        d_50 = m.c.price - 0.5 * bc_len
    else:
        d_50 = m.c.price + 0.5 * bc_len
    components.append(("0.5 BC", d_50))

    # Reciprocal AB=CD: C'den AB uzunluğu kadar geri
    if m.direction == "bull":
        d_recip = m.c.price - ab_len
    else:
        d_recip = m.c.price + ab_len
    components.append(("AB=CD", d_recip))

    # 0.618 retracement (stop bölgesi referansı)
    if m.direction == "bull":
        d_618 = m.c.price - 0.618 * bc_len
    else:
        d_618 = m.c.price + 0.618 * bc_len
    components.append(("0.618 BC (stop ref.)", d_618))

    prices = [p for _, p in components[:2]]  # PRZ sadece 0.5 ve AB=CD
    prz_low = min(prices)
    prz_high = max(prices)

    # Entry = D'nin gerçek seviyesi
    entry = m.d.price

    # SL = 0.618 retracement ötesi (BC'nin 0.618'i + buffer)
    sl_buffer = 0.05 * bc_len
    if m.direction == "bull":
        stop = d_618 - sl_buffer
    else:
        stop = d_618 + sl_buffer

    # TP = AB seviyesi (formasyon başlangıcı) - 0.382 ve 0.618 IPO
    if m.direction == "bull":
        # Bull: hedefler entry'nin üstünde
        # IPO: formasyon range = C - D
        range_cd = abs(m.c.price - entry)
        tp1 = entry + 0.382 * range_cd
        tp2 = entry + 0.618 * range_cd
    else:
        range_cd = abs(entry - m.c.price)
        tp1 = entry - 0.382 * range_cd
        tp2 = entry - 0.618 * range_cd

    return Setup(
        symbol=symbol, interval=interval,
        pattern_name="5-0", direction=m.direction,
        pivots={"X": m.x, "A": m.a, "B": m.b, "C": m.c, "D": m.d},
        b_ratio=m.b_ext_xa,
        c_ratio=m.c_ext_ab,
        d_ratio=m.d_retr_bc,
        bc_proj=0.5,  # tanımlayıcı
        cd_ab_ratio=m.cd_ab_ratio,
        ab_cd_equivalent=m.abcd_equivalent,
        prz_low=prz_low, prz_high=prz_high, prz_components=components,
        entry=entry, stop=stop, tp1=tp1, tp2=tp2,
        detected_at=int(time.time() * 1000),
        pattern_family="five_zero",
    )
