"""Sentetik mum dizisi üretici — bilinen XABCD pivot oranlarından.

`make_pivots` 3 oran (b_r, c_r, d_r) alır ve bunlardan tutarlı bir bull
XABCD üretir; bc_projection ratio doğal olarak çıkar. `to_bear` aynı
geometriyi yatayda yansıtır.
"""
from __future__ import annotations

ONE_HOUR_MS = 60 * 60 * 1000


# -------- pivot üretici --------

def make_pivots(
    b_r: float,
    c_r: float,
    d_r: float,
    xa: float = 20.0,
    x: float = 100.0,
) -> tuple[list[float], list[str]]:
    """Bull XABCD pivotları.

    Args:
        b_r: B'nin XA retracement oranı (0-1).
        c_r: C'nin AB retracement oranı (0-1).
        d_r: D'nin XA değeri (>0). <1: retracement, >1: extension.
        xa: XA bacağı uzunluğu (fiyat).
        x:  X noktası fiyatı.
    """
    a = x + xa
    b = a - b_r * xa
    c = b + c_r * (a - b)
    d = a - d_r * xa
    return [x, a, b, c, d], ["low", "high", "low", "high", "low"]


def to_bear(
    prices: list[float],
    kinds: list[str],
    pivot_high: float = 300.0,
) -> tuple[list[float], list[str]]:
    """Bull pivot setini yatayda yansıtarak bear üretir.

    Tüm oranlar aynı kalır (vertical mirror).
    """
    base = prices[0]
    bear_prices = [pivot_high - (p - base) for p in prices]
    bear_kinds = ["high" if k == "low" else "low" for k in kinds]
    return bear_prices, bear_kinds


# -------- hazır formasyon üreticileri --------
# Her biri spec'in oran bandlarına uyan c_r seçimiyle hazırlanmıştır.

def gartley_bull() -> tuple[list[float], list[str]]:
    """B=0.618, D=0.786, C=0.50 of AB → bc_proj ≈ 1.544 (Gartley bandında)."""
    return make_pivots(b_r=0.618, c_r=0.50, d_r=0.786)


def bat_bull() -> tuple[list[float], list[str]]:
    """B=0.50, D=0.886, C=0.50 → bc_proj=2.544 (Bat bandında)."""
    return make_pivots(b_r=0.50, c_r=0.50, d_r=0.886)


def alternate_bat_bull() -> tuple[list[float], list[str]]:
    """B=0.382, D=1.13 (extension), C=0.886 of AB → bc_proj=3.21 (Alt Bat bandında)."""
    return make_pivots(b_r=0.382, c_r=0.886, d_r=1.13)


def butterfly_bull() -> tuple[list[float], list[str]]:
    """B=0.786, D=1.27 (extension), C=0.50 → bc_proj=2.232 (Butterfly bandında)."""
    return make_pivots(b_r=0.786, c_r=0.50, d_r=1.27)


def crab_bull() -> tuple[list[float], list[str]]:
    """B=0.50, D=1.618 (extension), C=0.87 (deep) → bc_proj=3.57 (Crab bandında)."""
    return make_pivots(b_r=0.50, c_r=0.87, d_r=1.618)


def deep_crab_bull() -> tuple[list[float], list[str]]:
    """B=0.886, D=1.618 (extension), C=0.50 → bc_proj=2.652 (Deep Crab bandında)."""
    return make_pivots(b_r=0.886, c_r=0.50, d_r=1.618)


# -------- kline üretici --------

def make_xabcd_klines(
    pivot_prices: list[float],
    pivot_kinds: list[str],
    bars_per_leg: int = 12,
    base_time: int = 1_700_000_000_000,
    interval_ms: int = ONE_HOUR_MS,
) -> list[dict]:
    """5 pivot fiyatından sentetik mum dizisi üretir.

    Her bacakta `bars_per_leg` mum, fiyat doğrusal interpolasyonla geçer.
    Wick'ler küçük (bacağın %0.5'i) — pivot dışında ZigZag tetiklemez.
    """
    assert len(pivot_prices) == len(pivot_kinds) == 5

    klines: list[dict] = []
    t = base_time

    # İlk mum: pivot fiyatına eşit
    klines.append({
        "open_time": t, "close_time": t + interval_ms - 1,
        "open": pivot_prices[0], "high": pivot_prices[0],
        "low": pivot_prices[0], "close": pivot_prices[0],
        "volume": 100.0, "quote_volume": 1000.0,
    })
    t += interval_ms

    for i in range(1, 5):
        prev_price = pivot_prices[i - 1]
        cur_price = pivot_prices[i]
        going_up = cur_price > prev_price
        leg_size = abs(cur_price - prev_price)
        wick = leg_size * 0.005

        for j in range(1, bars_per_leg + 1):
            close = prev_price + (cur_price - prev_price) * (j / bars_per_leg)
            o = prev_price + (cur_price - prev_price) * ((j - 1) / bars_per_leg)
            if going_up:
                h = close
                l = min(o, close) - wick
            else:
                l = close
                h = max(o, close) + wick
            klines.append({
                "open_time": t, "close_time": t + interval_ms - 1,
                "open": o,
                "high": max(o, h),
                "low": min(o, l),
                "close": close,
                "volume": 100.0, "quote_volume": 1000.0,
            })
            t += interval_ms

    return klines
