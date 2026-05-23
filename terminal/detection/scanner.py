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
from terminal.detection.pivots import find_pivots
from terminal.detection.prz import compute_prz, compute_trade_levels
from terminal.quality.htf_ltf import alignment, detect_trend, htf_for
from terminal.quality.score import compute_q

log = logging.getLogger(__name__)

# TF başı varsayılan ZigZag eşikleri (yüzde olarak).
# Carney pivot'ları elle belirler; ZigZag eşiği bizim tahminimiz. Aşağıdaki
# değerler test edilmiş tatlı nokta: yeterince hassas (küçük pivot'ları
# kaçırmıyor) ama gürültüye boğmuyor.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "1m":  0.0025,
    "5m":  0.0040,
    "15m": 0.0075,
    "30m": 0.0110,
    "60m": 0.0150,
    "4h":  0.0220,
    "1d":  0.0400,
    "1W":  0.0700,
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
    if len(pivots) < 5:
        return []

    # HTF trendi (tüm setup'lar için aynı, bir kez hesapla)
    htf_interval = htf_for(interval)
    htf_trend: str | None = None
    if htf_klines is not None and htf_interval is not None:
        htf_trend = detect_trend(htf_klines)

    detected_at = int(time.time() * 1000)
    setups: list[Setup] = []

    for i in range(len(pivots) - 4):
        m = match_xabcd(pivots[i:i + 5])
        if m is None:
            continue

        prz = compute_prz(m)
        levels = compute_trade_levels(m, prz)
        q = m.quintet

        setup = Setup(
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
            htf_interval=htf_interval,
            htf_trend=htf_trend,
        )

        # Q skoru ve HTF uyumu
        qr = compute_q(setup, htf_trend=htf_trend)
        setup.q_score = qr.score
        setup.q_category = qr.category
        setup.q_components = qr.components
        setup.htf_aligned = alignment(setup.direction, htf_trend)
        setup.elenen = setup.htf_aligned is False  # explicit False, neutral değil

        setups.append(setup)

    return setups
