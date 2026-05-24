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
    """Entry, SL, TP seviyeleri.

    Entry: PRZ %40 derinlik (PRZ üst banttan PRZ aralığının %40'ı kadar içeri).
    Stop: Pattern stop (D_ideal ötesi, spec.stop_at_xa katında) yeterli derinde
          ise korunur; entry'ye göre yanlış taraftaysa PRZ ucu + %5 buffer.
    TP1 = B seviyesi (önceki swing — doğal ilk hedef, AB=CD ile uyumlu).
    TP2 = C seviyesi (tam retracement endpoint).

    Backtest optimizasyonu (BTC+ETH 15m 1 ay, 31 setup):
      D_ideal entry:        WR 50.0%, Tot +10.68R, Avg +0.67R
      PRZ %40 + Akıllı SL:  WR 64.7%, Tot +15.01R, Avg +0.88R
    """
    spec = m.spec
    q = m.quintet
    sign = _direction_sign(q.direction)
    xa_len = abs(q.a.price - q.x.price)

    prz_low = prz["prz_low"]
    prz_high = prz["prz_high"]
    prz_range = prz_high - prz_low

    # PRZ %40 derinlik entry
    if q.direction == "bull":
        entry = prz_high - 0.40 * prz_range
    else:
        entry = prz_low + 0.40 * prz_range

    # Akıllı SL: pattern stop yeterliyse onu kullan, değilse PRZ ucu + %5 buffer
    pattern_stop = q.a.price + sign * spec.stop_at_xa * xa_len
    buf = 0.05 * prz_range
    if q.direction == "bull":
        stop = pattern_stop if pattern_stop < entry else (prz_low - buf)
    else:
        stop = pattern_stop if pattern_stop > entry else (prz_high + buf)

    tp1 = q.b.price
    tp2 = q.c.price

    return {"entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2}
