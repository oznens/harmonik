"""Buffer üstünde gezip Setup listesi üreten ana orkestratör.

Stateless: her çağrıda kline listesini alır, ZigZag çalıştırır, ardışık
5'li pivot pencerelerinde formasyon arar, eşleşenleri Setup olarak döner.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from terminal.detection.matcher import match_xabcd
from terminal.detection.models import Setup
from terminal.detection.pivots import find_pivots
from terminal.detection.prz import compute_prz, compute_trade_levels

log = logging.getLogger(__name__)

# TF başı varsayılan ZigZag eşikleri (yüzde olarak)
DEFAULT_THRESHOLDS: dict[str, float] = {
    "1m": 0.003,
    "5m": 0.005,
    "15m": 0.010,
    "30m": 0.015,
    "60m": 0.020,
    "4h":  0.030,
    "1d":  0.050,
    "1W":  0.080,
}


def default_threshold(interval: str) -> float:
    return DEFAULT_THRESHOLDS.get(interval, 0.02)


def scan_klines(
    klines: list[dict[str, Any]],
    symbol: str,
    interval: str,
    zigzag_threshold: float | None = None,
) -> list[Setup]:
    """Mum dizisinden formasyonları çıkar.

    Args:
        klines: open_time/open/high/low/close/volume alanlı dict listesi.
        symbol: parite kodu (örn. "BTCUSDT").
        interval: aralık ("15m", "1h"/"60m", "4h", "1d"...).
        zigzag_threshold: özelse yüzde (örn. 0.02). Yoksa interval'a göre varsayılan.

    Returns:
        Setup listesi. Aynı pivot kombinasyonu birden fazla kez girmez.
    """
    threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
    pivots = find_pivots(klines, threshold)
    if len(pivots) < 5:
        return []

    detected_at = int(time.time() * 1000)
    setups: list[Setup] = []

    for i in range(len(pivots) - 4):
        m = match_xabcd(pivots[i:i + 5])
        if m is None:
            continue

        prz = compute_prz(m)
        levels = compute_trade_levels(m, prz)
        q = m.quintet

        setups.append(Setup(
            symbol=symbol,
            interval=interval,
            pattern_name=m.spec.name,
            direction=q.direction,
            pivots={"X": q.x, "A": q.a, "B": q.b, "C": q.c, "D": q.d},
            b_ratio=m.b_ratio,
            c_ratio=m.c_ratio,
            d_ratio=m.d_ratio,
            bc_proj=m.bc_proj,
            cd_ab_ratio=m.cd_ab_ratio,
            ab_cd_equivalent=m.ab_cd_equivalent,
            prz_low=prz["prz_low"],
            prz_high=prz["prz_high"],
            prz_components=prz["prz_components"],
            entry=levels["entry"],
            stop=levels["stop"],
            tp1=levels["tp1"],
            tp2=levels["tp2"],
            detected_at=detected_at,
        ))

    return setups
