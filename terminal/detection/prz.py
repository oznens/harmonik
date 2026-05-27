"""PRZ (Potential Reversal Zone) ve işlem seviyeleri hesaplayıcı."""
from __future__ import annotations

from terminal.detection.matcher import MatchResult


def _direction_sign(direction: str) -> int:
    """Bull formasyonda fiyat aşağı yönde projekte edilir (sign=-1)."""
    return -1 if direction == "bull" else 1


def compute_prz(m: MatchResult) -> dict:
    """PRZ aralığını ve bileşenlerini hesapla.

    Bileşenler:
      - D = ideal XA retracement/extension (tanımlayıcı limit)
      - AB=CD ve alternatif katları (1.27 AB=CD, 1.618 AB=CD — spec'e göre)
      - BC projection: pattern bandında 1-2 ana değer
    """
    spec = m.spec
    q = m.quintet
    sign = _direction_sign(q.direction)

    xa_len = abs(q.a.price - q.x.price)
    ab_len = abs(q.a.price - q.b.price)
    bc_len = abs(q.c.price - q.b.price)

    components: list[tuple[str, float]] = []

    # 1. Tanımlayıcı limit: D = ideal XA
    d_ideal_price = q.a.price + sign * spec.d_ideal * xa_len
    components.append((f"{spec.d_ideal:.3f} XA", d_ideal_price))

    # 2. AB=CD ve alternatif katları
    for ratio in spec.ab_cd_target_ratios:
        label = "AB=CD" if ratio == 1.0 else f"{ratio:.3g} AB=CD"
        components.append((label, q.c.price + sign * ratio * ab_len))

    # 3. BC projection — pattern bandının uç değerlerinde 2 nokta
    for proj in (spec.bc_proj_min, spec.bc_proj_max):
        components.append((f"{proj:.3g} BC", q.c.price + sign * proj * bc_len))

    prices = [p for _, p in components]
    return {
        "prz_low": min(prices),
        "prz_high": max(prices),
        "prz_components": components,
        "d_ideal_price": d_ideal_price,
    }


def compute_trade_levels(m: MatchResult, prz: dict) -> dict:
    """Entry, SL, TP seviyeleri — PDF Trading Strategy Guides + Carney spec.

    Entry: D pivot fiyatı (Carney "limit emir D'de" + PDF tüm pattern'lerde).
    Stop: Pattern stop (PDF SL kurallarına göre spec.stop_at_xa katında).
    TP1: B noktası (önceki swing — PDF Butterfly/Gartley/Crab için ana hedef).
         Bat istisnası: TP1=C (PDF "Wave C and A" stratejisi).
    TP2: A noktası (formasyon başlangıcı — PDF'in en uzak yapısal hedefi).

    NEAR örneğinden ders: PRZ %40 derinlik entry'de fiyat D'ye değmeden
    yukarı uçuyordu → setup kaçırıldı. D pivot entry tetiklenmeyi maksimum
    yapar (PDF Carney mantığı).
    """
    spec = m.spec
    q = m.quintet
    sign = _direction_sign(q.direction)
    xa_len = abs(q.a.price - q.x.price)

    entry = q.d.price

    # SL: pattern stop (A noktasının ötesi, spec.stop_at_xa cinsinden)
    stop = q.a.price + sign * spec.stop_at_xa * xa_len

    # TP'ler: Bat için TP1=C (PDF "Wave C and Wave A" stratejisi);
    # diğer XABCD'lerde TP1=B (önceki swing — Butterfly/Gartley/Crab/...).
    if spec.name == "Bat":
        tp1 = q.c.price
    else:
        tp1 = q.b.price
    tp2 = q.a.price  # A noktası: formasyon başlangıç swing, en uzak hedef

    return {"entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2}
