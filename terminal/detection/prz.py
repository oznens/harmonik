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

    Entry: tanımlayıcı limit (D = ideal XA).
    Stop: D'nin ötesi, spec.stop_at_xa katında.
    TP1/TP2: formasyon uç noktalarından 0.382 / 0.618 retracement (IPO).
    """
    spec = m.spec
    q = m.quintet
    sign = _direction_sign(q.direction)
    xa_len = abs(q.a.price - q.x.price)

    entry = prz["d_ideal_price"]
    stop = q.a.price + sign * spec.stop_at_xa * xa_len

    # Formasyon uç noktaları
    if q.direction == "bull":
        formation_high = q.a.price
        formation_low = min(q.x.price, q.d.price, prz["prz_low"])
        span = formation_high - formation_low
        tp1 = formation_low + 0.382 * span
        tp2 = formation_low + 0.618 * span
    else:
        formation_low = q.a.price
        formation_high = max(q.x.price, q.d.price, prz["prz_high"])
        span = formation_high - formation_low
        tp1 = formation_high - 0.382 * span
        tp2 = formation_high - 0.618 * span

    return {"entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2}
