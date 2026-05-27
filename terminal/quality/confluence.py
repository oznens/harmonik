"""Confluence Agent — Setup'a RSI ve hacim onayı ekler.

PDF Trading Strategy Guides Agent-3 önerisi: PRZ'de RSI divergence + hacim
artışı tespit etmek, nihai AL/SAT sinyali kalitesini ölçmek.

Setup'a confluence_score (0-100) eklenir:
  - RSI position    (35 puan): bull setupta RSI < 30 (oversold) ideal
  - RSI divergence  (35 puan): fiyat dipte ama RSI yükseliyorsa bull divergence
  - Volume spike    (30 puan): entry barında hacim 20-bar ortalamasının üstü

Skor 0-100. Yüksek = güçlü confluence. Filtre için: --min-confluence X.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ConfluenceResult:
    score: int                       # 0-100
    components: dict[str, float]     # bileşen puanları
    rsi_at_d: float | None           # D pivot anındaki RSI (debug)
    volume_ratio: float | None       # entry barı / 20-bar avg


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI. closes[0..n-1] → RSI[0..n-1] (ilk period değer NaN'a denk).

    İlk period kadar 0 (geçersiz), sonra Wilder smoothing.
    """
    n = len(closes)
    if n <= period:
        return [0.0] * n
    rsi = [0.0] * n
    gains = 0.0
    losses = 0.0
    # İlk period için ortalama gain/loss
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100 - (100 / (1 + rs))
    # Wilder smoothing
    for i in range(period + 1, n):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = -min(diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def compute_confluence(
    direction: str,
    d_idx: int,
    klines: list[dict[str, Any]],
    b_idx: int | None = None,
) -> ConfluenceResult:
    """Setup için RSI + hacim confluence skorunu hesapla.

    Args:
        direction: "bull" veya "bear".
        d_idx: D pivot'unun klines içindeki indeksi.
        klines: tüm bar dizisi (D dahil).
        b_idx: B pivot'unun indeksi — varsa RSI divergence kontrolü yapılır.

    Returns:
        ConfluenceResult (score 0-100, bileşen detayları).
    """
    components: dict[str, float] = {
        "rsi_position": 0.0,
        "rsi_divergence": 0.0,
        "volume_spike": 0.0,
    }
    rsi_at_d: float | None = None
    volume_ratio: float | None = None

    if d_idx < 14 or d_idx >= len(klines):
        return ConfluenceResult(0, components, None, None)

    closes = [k["close"] for k in klines[: d_idx + 1]]
    rsi_series = _rsi(closes, period=14)
    rsi_at_d = rsi_series[d_idx] if d_idx < len(rsi_series) else None

    # 1) RSI pozisyon: bull → RSI<30 oversold; bear → RSI>70 overbought
    if rsi_at_d is not None and rsi_at_d > 0:
        if direction == "bull":
            if rsi_at_d <= 30:
                components["rsi_position"] = 35.0
            elif rsi_at_d <= 40:
                components["rsi_position"] = 25.0
            elif rsi_at_d <= 50:
                components["rsi_position"] = 15.0
        else:
            if rsi_at_d >= 70:
                components["rsi_position"] = 35.0
            elif rsi_at_d >= 60:
                components["rsi_position"] = 25.0
            elif rsi_at_d >= 50:
                components["rsi_position"] = 15.0

    # 2) RSI divergence: B'den D'ye fiyat aşağı/yukarı ama RSI ters yönde
    if b_idx is not None and 14 <= b_idx < d_idx and rsi_at_d is not None:
        rsi_at_b = rsi_series[b_idx] if b_idx < len(rsi_series) else None
        price_b = klines[b_idx]["low" if direction == "bull" else "high"]
        price_d = klines[d_idx]["low" if direction == "bull" else "high"]
        if rsi_at_b is not None:
            if direction == "bull":
                # Bull divergence: D < B (yeni dip), ama RSI(D) > RSI(B)
                if price_d < price_b and rsi_at_d > rsi_at_b:
                    components["rsi_divergence"] = 35.0
            else:
                # Bear divergence: D > B (yeni tepe), ama RSI(D) < RSI(B)
                if price_d > price_b and rsi_at_d < rsi_at_b:
                    components["rsi_divergence"] = 35.0

    # 3) Hacim spike: D barı / 20-bar ortalama
    if d_idx >= 20:
        recent_vols = [klines[i].get("volume", 0) for i in range(d_idx - 20, d_idx)]
        avg_vol = sum(recent_vols) / 20 if recent_vols else 0
        d_vol = klines[d_idx].get("volume", 0)
        if avg_vol > 0:
            volume_ratio = d_vol / avg_vol
            if volume_ratio >= 2.0:
                components["volume_spike"] = 30.0
            elif volume_ratio >= 1.5:
                components["volume_spike"] = 20.0
            elif volume_ratio >= 1.2:
                components["volume_spike"] = 10.0

    score = int(round(sum(components.values())))
    return ConfluenceResult(
        score=max(0, min(100, score)),
        components={k: round(v, 1) for k, v in components.items()},
        rsi_at_d=round(rsi_at_d, 1) if rsi_at_d is not None else None,
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
    )
