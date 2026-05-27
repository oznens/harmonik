"""Cypher formasyonu (Darren Oglesbee).

Noktalar: X, A, B, C, D (D = tamamlanma, entry).
Kaynak: "The Ultimate Harmonic Pattern Trading Guides" (Trading Strategy Guides).

Cypher'in DIĞER XABCD AİLESİNDEN FARKI:
  - C noktası A'nın ÖTESİNDE (bull: C > A, bear: C < A) — XA extension!
  - D noktası XC retracement'i (XA değil, AB değil — XC swing!)

Kurallar:
  - AB = 0.382-0.618 retracement of XA (Bat'a benzer)
  - BC = 1.272-1.414 extension of XA (C noktası A'nın üstüne/altına çıkar)
  - CD = 0.786 retracement of XC swing (yapısal limit)

Pivot yapısı (alternating, 5 pivot):
  Bull Cypher:  X(low),  A(high), B(low),  C(high — A'dan yüksek), D(low)
  Bear Cypher:  X(high), A(low),  B(high), C(low — A'dan düşük),    D(high)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot

# Cypher ratio aralıkları
AB_RETR_XA_MIN = 0.382
AB_RETR_XA_MAX = 0.618
# C noktasının X'ten konumu, XA cinsinden (Cypher'in tanımlayıcısı: C, A'nın üstüne çıkar)
# PDF: "BC is Fibonacci extension of XA leg" — aslında C'nin pozisyonu kastediliyor.
C_POS_XA_MIN = 1.272
C_POS_XA_MAX = 1.414
D_RETR_XC_TARGET = 0.786
D_RETR_XC_TOLERANCE = 0.05  # ±5pp tolerance

# SL için: D'nin ötesi (XC'nin %0.886'sı)
SL_AT_XC = 0.886


@dataclass
class CypherMatchResult:
    direction: str
    x: Pivot
    a: Pivot
    b: Pivot
    c: Pivot
    d: Pivot
    ab_retr_xa: float    # B'nin XA retracement'i
    c_pos_xa: float      # C'nin X'ten konumu, XA cinsinden (>1: A'nın ötesinde)
    d_retr_xc: float     # D'nin XC retracement'i (~0.786)


def _is_alternating(pivots: list[Pivot]) -> bool:
    for i in range(1, len(pivots)):
        if pivots[i].kind == pivots[i - 1].kind:
            return False
    return True


def match_cypher(p5: list[Pivot]) -> CypherMatchResult | None:
    """5 ardışık pivot Cypher formasyonuna uyuyor mu?"""
    if len(p5) != 5 or not _is_alternating(p5):
        return None
    x, a, b, c, d = p5

    if x.kind == "low":
        # Bull Cypher: X(low), A(high), B(low), C(high), D(low)
        direction = "bull"
        # Geometri: A yukarı, B retr aşağı, C A'nın ÜSTÜNDE (extension), D aşağı
        if not (a.price > x.price             # XA up
                and x.price <= b.price < a.price  # B XA içinde retracement
                and c.price > a.price          # C A'nın üstünde (KRİTİK)
                and d.price < c.price          # D aşağı (XC retracement)
                and d.price > x.price):        # D X'in üstünde (XC retracement <1)
            return None
        xa_len = a.price - x.price
        ab_retr = (a.price - b.price) / xa_len if xa_len > 0 else 0
        c_pos = (c.price - x.price) / xa_len if xa_len > 0 else 0  # >1 = A'nın üstünde
        xc_len = c.price - x.price
        d_retr = (c.price - d.price) / xc_len if xc_len > 0 else 0
    else:
        # Bear Cypher: X(high), A(low), B(high), C(low), D(high)
        direction = "bear"
        if not (a.price < x.price             # XA down
                and a.price < b.price <= x.price  # B XA içinde retracement
                and c.price < a.price          # C A'nın altında (KRİTİK)
                and d.price > c.price          # D yukarı (XC retracement)
                and d.price < x.price):        # D X'in altında
            return None
        xa_len = x.price - a.price
        ab_retr = (b.price - a.price) / xa_len if xa_len > 0 else 0
        c_pos = (x.price - c.price) / xa_len if xa_len > 0 else 0  # >1 = A'nın altında
        xc_len = x.price - c.price
        d_retr = (d.price - c.price) / xc_len if xc_len > 0 else 0

    # Oran kontrolleri
    if not (AB_RETR_XA_MIN <= ab_retr <= AB_RETR_XA_MAX):
        return None
    if not (C_POS_XA_MIN <= c_pos <= C_POS_XA_MAX):
        return None
    if not (abs(d_retr - D_RETR_XC_TARGET) <= D_RETR_XC_TOLERANCE):
        return None

    return CypherMatchResult(
        direction=direction,
        x=x, a=a, b=b, c=c, d=d,
        ab_retr_xa=ab_retr, c_pos_xa=c_pos, d_retr_xc=d_retr,
    )


def build_cypher_setup(m: CypherMatchResult, symbol: str, interval: str) -> Setup:
    """Cypher match'ten Setup nesnesi üret."""
    sign = -1 if m.direction == "bull" else 1
    xc_len = abs(m.c.price - m.x.price)

    # PRZ bileşenleri: XC retracement seviyeleri (0.786 ana, 0.707 ve 0.886 destek)
    components: list[tuple[str, float]] = []
    for ratio in (0.707, 0.786, 0.886):
        d_candidate = m.c.price + sign * ratio * xc_len
        components.append((f"{ratio:.3g} XC", d_candidate))

    prices = [p for _, p in components]
    prz_low = min(prices)
    prz_high = max(prices)

    # Entry: D pivot fiyatı (PDF "Step #2: Enter at D point" — Cypher'de
    # D = 0.786 XC retracement).
    entry = m.d.price

    # SL: X altı/üstü (PDF "Step #3: Place SL below wave X"). X swing'i
    # kırılırsa pattern invalidate.
    xa_len = abs(m.a.price - m.x.price)
    sl_buf = 0.05 * xa_len  # %5 XA buffer
    if m.direction == "bull":
        stop = m.x.price - sl_buf
    else:
        stop = m.x.price + sl_buf

    # TP: A noktası (PDF "Step #4: Take profit once we reach point A").
    # TP2 = B (Cypher'de C, A'nın ötesinde olduğu için B daha derin geri
    # çekiliş hedefi).
    tp1 = m.a.price
    tp2 = m.b.price

    return Setup(
        symbol=symbol, interval=interval,
        pattern_name="Cypher", direction=m.direction,
        pivots={"X": m.x, "A": m.a, "B": m.b, "C": m.c, "D": m.d},
        b_ratio=m.ab_retr_xa,    # B'nin XA retr
        c_ratio=m.c_pos_xa,      # C'nin XA pozisyonu (Cypher'in tanımlayıcısı, >1)
        d_ratio=m.d_retr_xc,     # D'nin XC retr (en kritik)
        bc_proj=0.0,             # Cypher'de BC projection kavramı farklı
        cd_ab_ratio=0.0,         # Cypher'de AB=CD onayı yok
        ab_cd_equivalent=False,
        prz_low=prz_low, prz_high=prz_high, prz_components=components,
        entry=entry, stop=stop, tp1=tp1, tp2=tp2,
        detected_at=int(time.time() * 1000),
        pattern_family="cypher",
    )
