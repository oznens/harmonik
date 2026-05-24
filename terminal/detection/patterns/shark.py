"""Shark formasyonu (Carney 2011, Vol.3).

Noktalar: 0, X, A, B, C (C = tamamlanma, entry).
notlar/06-shark.md kurallari:
  - A = 0X bacağının 0.382-0.618 retracement'i
  - B = XA'nın 1.13-1.618 ekstansiyonu (Extreme Harmonic Impulse Wave)
    → B, X'in OTESINE gecer (bull Shark'ta C tarafına dogru)
  - C = AB'nin 1.618-2.24 ekstansiyonu VE 0B'nin 0.886-1.13'u
    → C iki sart aynı anda saglar
  - Bull Shark: C'de long (C en dusuk seviye)
  - Bear Shark: C'de short (C en yuksek seviye)
  - SL: 1.13 ekstansiyonun hemen otesi
  - TP: %50 retracement veya Reciprocal AB=CD (hangisi once)

Pivot yapisi (alternating, 5 pivot):
  Bull Shark:  0(low),  X(high), A(low),  B(high), C(low)  → C cok dusuk
  Bear Shark:  0(high), X(low),  A(high), B(low),  C(high) → C cok yuksek
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot

# Shark oran aralikları (notlar/06-shark.md, Vol.3)
A_RETR_MIN = 0.382
A_RETR_MAX = 0.618
B_EXT_MIN = 1.13
B_EXT_MAX = 1.618
C_EXT_AB_MIN = 1.618
C_EXT_AB_MAX = 2.24
C_RETR_0B_MIN = 0.886
C_RETR_0B_MAX = 1.13


@dataclass
class SharkMatchResult:
    direction: str       # "bull" or "bear"
    p0: Pivot
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    a_retr_0x: float     # A'nin 0X retracement'i
    b_ext_xa: float      # B'nin XA extension'i
    c_ext_ab: float      # C'nin AB extension'i
    c_retr_0b: float     # C'nin 0B retracement/extension'i


def _is_alternating(pivots: list[Pivot]) -> bool:
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def match_shark(p5: list[Pivot]) -> SharkMatchResult | None:
    """5 ardışık pivot Shark formasyonuna uyuyor mu?

    Pivot dizilimi alternating olmali; ilk pivot'in kind'i yon belirler.
    """
    if len(p5) != 5 or not _is_alternating(p5):
        return None
    p0, x, a, b, c = p5

    if p0.kind == "low":
        # Bull Shark: 0(low), X(high), A(low), B(high), C(low)
        direction = "bull"
        # Geometri: X yukarı, A retr aşağı, B X'in üstünde (impuls). C
        # 0.886-1.13 of 0B bandında — bu zaten ratio kontrolünde yapılır.
        if not (x.price > p0.price
                and p0.price <= a.price < x.price
                and b.price > x.price
                and c.price < b.price):
            return None
        # Oranlar
        zero_x_len = x.price - p0.price
        a_retr = (x.price - a.price) / zero_x_len
        xa_len = x.price - a.price
        b_ext = (b.price - a.price) / xa_len if xa_len > 0 else 0
        ab_len = b.price - a.price
        c_ext_ab = (b.price - c.price) / ab_len if ab_len > 0 else 0
        zero_b_len = b.price - p0.price
        c_retr_0b = (b.price - c.price) / zero_b_len if zero_b_len > 0 else 0
    else:
        # Bear Shark: 0(high), X(low), A(high), B(low), C(high)
        direction = "bear"
        if not (x.price < p0.price
                and x.price < a.price <= p0.price
                and b.price < x.price
                and c.price > b.price):
            return None
        zero_x_len = p0.price - x.price
        a_retr = (a.price - x.price) / zero_x_len
        xa_len = a.price - x.price
        b_ext = (a.price - b.price) / xa_len if xa_len > 0 else 0
        ab_len = a.price - b.price
        c_ext_ab = (c.price - b.price) / ab_len if ab_len > 0 else 0
        zero_b_len = p0.price - b.price
        c_retr_0b = (c.price - b.price) / zero_b_len if zero_b_len > 0 else 0

    # Oran kontrolleri
    if not (A_RETR_MIN <= a_retr <= A_RETR_MAX):
        return None
    if not (B_EXT_MIN <= b_ext <= B_EXT_MAX):
        return None
    if not (C_EXT_AB_MIN <= c_ext_ab <= C_EXT_AB_MAX):
        return None
    if not (C_RETR_0B_MIN <= c_retr_0b <= C_RETR_0B_MAX):
        return None

    return SharkMatchResult(
        direction=direction,
        p0=p0, x=x, a=a, b=b, c=c,
        a_retr_0x=a_retr, b_ext_xa=b_ext,
        c_ext_ab=c_ext_ab, c_retr_0b=c_retr_0b,
    )


def build_shark_setup(m: SharkMatchResult, symbol: str, interval: str) -> Setup:
    """Shark match'ten Setup nesnesi üret.

    Setup.pivots eşleştirme: X=0, A=X, B=A, C=B, D=C (5-slot XABCD'ye yerleştir).
    """
    sign = -1 if m.direction == "bull" else 1
    zero_b_len = abs(m.b.price - m.p0.price)
    ab_len = abs(m.a.price - m.b.price)

    # PRZ bileşenleri — C'nin iki tanımlayıcı oranı
    components: list[tuple[str, float]] = []
    # 0B retracement'leri (0.886 ve 1.0 ve 1.13)
    for ratio in (0.886, 1.0, 1.13):
        c_candidate = m.b.price + sign * ratio * zero_b_len
        components.append((f"{ratio:.3g} 0B", c_candidate))
    # AB extension'lar (1.618, 2.0, 2.24)
    for ratio in (1.618, 2.0, 2.24):
        c_candidate = m.b.price + sign * ratio * ab_len
        components.append((f"{ratio:.3g} AB", c_candidate))

    prices = [p for _, p in components]
    prz_low = min(prices)
    prz_high = max(prices)

    # Entry = C'nin gerçek seviyesi (zaten tetiklenmiş pivot)
    entry = m.c.price

    # SL: 1.13 ekstansiyonun hemen ötesi (notlar/06-shark.md kural 4)
    sl_level = m.b.price + sign * 1.13 * zero_b_len
    # Küçük bir buffer ekle (%2 of 0B length)
    stop = sl_level + sign * 0.02 * zero_b_len

    # TP: %50 retracement veya Reciprocal AB=CD (hangisi önce)
    # %50 retracement of C → 0B yönünde
    tp_50 = m.c.price - sign * 0.5 * abs(m.b.price - m.c.price)
    # Reciprocal AB=CD: C'den AB uzunluğu kadar geri
    tp_recip = m.c.price - sign * ab_len
    # Bull (sign=-1) için TP yukarıda; "hangisi önce" = entry'ye en yakın
    if m.direction == "bull":
        tp1 = min(tp_50, tp_recip)  # en yakın yukarı target
        tp2 = max(tp_50, tp_recip)
    else:
        tp1 = max(tp_50, tp_recip)  # en yakın aşağı target
        tp2 = min(tp_50, tp_recip)

    return Setup(
        symbol=symbol, interval=interval,
        pattern_name="Shark", direction=m.direction,
        # XABCD slotuna mapleme: X=0, A=X, B=A, C=B, D=C
        pivots={"X": m.p0, "A": m.x, "B": m.a, "C": m.b, "D": m.c},
        b_ratio=m.a_retr_0x,    # A'nın 0X retr (eski adıyla "B" yerine)
        c_ratio=m.b_ext_xa,     # B'nin XA ext (eski adıyla "C" yerine)
        d_ratio=m.c_retr_0b,    # C'nin 0B retr (en kritik)
        bc_proj=m.c_ext_ab,     # C'nin AB ext
        cd_ab_ratio=0.0,        # Shark'ta AB=CD yok
        ab_cd_equivalent=False,
        prz_low=prz_low, prz_high=prz_high, prz_components=components,
        entry=entry, stop=stop, tp1=tp1, tp2=tp2,
        detected_at=int(time.time() * 1000),
        pattern_family="shark",
    )
