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
from terminal.detection.patterns.five_zero import build_five_zero_setup, match_five_zero
from terminal.detection.patterns.shark import build_shark_setup, match_shark
from terminal.detection.patterns.three_drives import (
    build_three_drives_setup,
    match_three_drives,
)
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

    # 3) 5-pivot pencerelerde Shark (0-X-A-B-C, farklı kural)
    for i in range(len(pivots) - 4):
        m_sh = match_shark(pivots[i:i + 5])
        if m_sh is None:
            continue
        setup = build_shark_setup(m_sh, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        # Aynı 5 pivot XABCD olarak da eşleşmişse atla (daha katı XABCD önceliklidir)
        key = (m_sh.p0.time, m_sh.x.time, m_sh.a.time, m_sh.b.time, m_sh.c.time)
        already = any(k[1:6] == key for k in seen_keys)
        if already:
            continue
        _finalize(setup, htf_trend)
        setups.append(setup)

    # 4) 5-pivot pencerelerde 5-0 (X-A-B-C-D, B XA extension)
    for i in range(len(pivots) - 4):
        m_fz = match_five_zero(pivots[i:i + 5])
        if m_fz is None:
            continue
        setup = build_five_zero_setup(m_fz, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        key = (m_fz.x.time, m_fz.a.time, m_fz.b.time, m_fz.c.time, m_fz.d.time)
        already = any(k[1:6] == key for k in seen_keys)
        if already:
            continue
        _finalize(setup, htf_trend)
        setups.append(setup)

    # 5) 5-pivot pencerelerde Three Drives (3 itiş + 2 düzeltme)
    interval_ms_map = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
                       "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1W": 604_800_000}
    interval_ms = interval_ms_map.get(interval, 3_600_000)
    for i in range(len(pivots) - 4):
        m_td = match_three_drives(pivots[i:i + 5], interval_ms=interval_ms)
        if m_td is None:
            continue
        setup = build_three_drives_setup(m_td, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        key = (m_td.d1.time, m_td.r1.time, m_td.d2.time, m_td.r2.time, m_td.d3.time)
        already = any(k[1:6] == key for k in seen_keys)
        if already:
            continue
        _finalize(setup, htf_trend)
        setups.append(setup)

    return setups


# Pattern-spesifik HTF zıt elenen listesi.
# Backtest (3 ay × 5 parite × 3 TF) verisinde HTF zıt durumda net negatif R
# üreten pattern'ler. Diğer harmonik desenler mean-reversion doğası gereği
# HTF zıt'ta daha iyi performe ediyor (toplam +18.52R zıt vs +11.28R uyumlu)
# — bu yüzden default olarak elenen sayılmıyor.
HTF_OPPOSITE_PENALIZED: frozenset[str] = frozenset({
    "1.62 AB=CD",  # HTF zıt: N=28, WR=33.3%, TotR=-7.43, AvgR=-0.31
})


def _is_elenen(setup: Setup) -> bool:
    """Setup elenen havuzuna mı düşmeli? Pattern-spesifik kötü kombinasyonlar."""
    if setup.htf_aligned is False and setup.pattern_name in HTF_OPPOSITE_PENALIZED:
        return True
    return False


def _finalize(setup: Setup, htf_trend: str | None) -> None:
    """Setup'a Q skoru ve HTF uyumu doldur (in-place)."""
    qr = compute_q(setup, htf_trend=htf_trend)
    setup.q_score = qr.score
    setup.q_category = qr.category
    setup.q_components = qr.components
    setup.htf_aligned = alignment(setup.direction, htf_trend)
    setup.elenen = _is_elenen(setup)
