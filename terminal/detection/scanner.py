"""Buffer üstünde gezip Setup listesi üreten ana orkestratör.

Stateless: her çağrıda kline listesini alır, ZigZag çalıştırır, ardışık
5'li pivot pencerelerinde formasyon arar, eşleşenleri Setup olarak döner.
İsteğe bağlı HTF mum dizisi verilirse Q skoru ve elenen bayrağı hesaplanır.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from terminal.detection.matcher import match_xabcd
from terminal.detection.models import Setup
from terminal.detection.patterns.abcd import build_abcd_setup, match_abcd
from terminal.detection.pivots import find_pivots
from terminal.detection.prz import compute_prz, compute_trade_levels
from terminal.quality.htf_ltf import alignment, detect_trend, htf_for
from terminal.quality.score import compute_q

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
    htf_klines: list[dict[str, Any]] | None = None,
) -> list[Setup]:
    """Mum dizisinden formasyonları çıkar; opsiyonel HTF ile Q skoru hesapla.

    Args:
        klines: setup TF'sinin mum dizisi (eski → yeni).
        symbol: parite kodu (örn. "BTCUSDT").
        interval: setup aralığı ("15m", "60m"/"1h", "4h", "1d"...).
        zigzag_threshold: özelse yüzde (örn. 0.02). Yoksa interval varsayılanı.
        htf_klines: üst zaman dilimi mum dizisi (HTF trend için). Yoksa
                    Q skorunda HTF bileşeni 0 olur, elenen tespiti yapılmaz.

    Returns:
        Setup listesi (Q skoru ve HTF bilgisi doldurulmuş).
    """
    threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
    pivots = find_pivots(klines, threshold)
    if len(pivots) < 4:
        return []

    # HTF trendi (tüm setup'lar için aynı, bir kez hesapla)
    htf_interval = htf_for(interval)
    htf_trend: str | None = None
    if htf_klines is not None and htf_interval is not None:
        htf_trend = detect_trend(htf_klines)

    detected_at = int(time.time() * 1000)
    setups: list[Setup] = []
    seen_keys: set[tuple] = set()  # aynı pivot kombinasyonu birden fazla pattern olarak eşleşmesin

    # 1) 5-pivot pencerelerde XABCD ailesi (Gartley/Bat/Butterfly/Crab/...)
    for i in range(len(pivots) - 4):
        m = match_xabcd(pivots[i:i + 5])
        if m is None:
            continue
        q = m.quintet
        prz = compute_prz(m)
        levels = compute_trade_levels(m, prz)
        setup = Setup(
            symbol=symbol, interval=interval,
            pattern_name=m.spec.name, direction=q.direction,
            pivots={"X": q.x, "A": q.a, "B": q.b, "C": q.c, "D": q.d},
            b_ratio=m.b_ratio, c_ratio=m.c_ratio, d_ratio=m.d_ratio,
            bc_proj=m.bc_proj, cd_ab_ratio=m.cd_ab_ratio,
            ab_cd_equivalent=m.ab_cd_equivalent,
            prz_low=prz["prz_low"], prz_high=prz["prz_high"],
            prz_components=prz["prz_components"],
            entry=levels["entry"], stop=levels["stop"],
            tp1=levels["tp1"], tp2=levels["tp2"],
            detected_at=detected_at,
            htf_interval=htf_interval, htf_trend=htf_trend,
            pattern_family="xabcd",
        )
        _finalize(setup, htf_trend)
        setups.append(setup)
        seen_keys.add((m.spec.name, q.x.time, q.a.time, q.b.time, q.c.time, q.d.time))

    # 2) 4-pivot pencerelerde standalone AB=CD
    for i in range(len(pivots) - 3):
        m_abcd = match_abcd(pivots[i:i + 4])
        if m_abcd is None:
            continue
        setup = build_abcd_setup(m_abcd, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        # Aynı pivotları XABCD olarak da eşleşmişse atla (XABCD'nin parçası zaten)
        key = ("ABCD", setup.pivots["A"].time, setup.pivots["B"].time,
               setup.pivots["C"].time, setup.pivots["D"].time)
        if any(k[2:] == key[1:] for k in seen_keys):
            continue
        _finalize(setup, htf_trend)
        setups.append(setup)

    return setups


def _finalize(setup: Setup, htf_trend: str | None) -> None:
    """Setup'a Q skoru ve HTF uyumu doldur (in-place)."""
    qr = compute_q(setup, htf_trend=htf_trend)
    setup.q_score = qr.score
    setup.q_category = qr.category
    setup.q_components = qr.components
    setup.htf_aligned = alignment(setup.direction, htf_trend)
    setup.elenen = setup.htf_aligned is False
