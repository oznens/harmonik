"""HTF (Higher Time Frame) trend tespiti + HTF/LTF eşleştirme.

LTF (setup TF'si) → HTF haritası terminal vizyonundaki "HTF-LTF Kontrol
Sistemi"ne uygun. HTF trendi, setup yönüyle uyuşuyorsa setup geçerli;
uyuşmuyorsa "Elenen Setup" havuzuna gider (Q skoru düşer).
"""
from __future__ import annotations

from typing import Any

# LTF → HTF eşleştirmesi (kullanıcının "üst zaman dilimi" mantığı).
HTF_MAPPING: dict[str, str] = {
    "1m":  "15m",
    "5m":  "30m",
    "15m": "60m",
    "30m": "4h",
    "60m": "4h",
    "4h":  "1d",
    "1d":  "1W",
}


def htf_for(interval: str) -> str | None:
    """Verilen LTF için HTF aralığını döner (yoksa None)."""
    return HTF_MAPPING.get(interval)


def _ema(values: list[float], period: int) -> list[float]:
    """Üstel hareketli ortalama. İlk `period` mum SMA olarak başlar."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    out = [ema_val]
    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)
        out.append(ema_val)
    return out


def detect_trend(klines: list[dict[str, Any]],
                 fast: int = 20, slow: int = 50,
                 neutral_pct: float = 0.003) -> str:
    """Son N mum üstünde EMA(fast) vs EMA(slow) ile basit trend tespiti.

    Returns:
        'bull', 'bear' veya 'neutral'.
    """
    if len(klines) < slow + 1:
        return "neutral"
    closes = [k["close"] for k in klines[-(slow + 50):]]  # son ~slow+50 mum
    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    if not ema_f or not ema_s:
        return "neutral"
    # son değer karşılaştırması — pozisyonları hizala
    fast_last = ema_f[-1]
    slow_last = ema_s[-1]
    if slow_last == 0:
        return "neutral"
    diff = (fast_last - slow_last) / slow_last
    if abs(diff) < neutral_pct:
        return "neutral"
    return "bull" if diff > 0 else "bear"


def alignment(setup_direction: str, htf_trend: str | None) -> bool | None:
    """Setup yönü HTF trendiyle uyumlu mu?

    Returns:
        True: uyumlu (HTF trendi setup yönünü destekliyor).
        False: zıt (setup HTF trendine ters → Elenen).
        None: HTF bilinmiyor veya neutral.
    """
    if htf_trend is None or htf_trend == "neutral":
        return None
    if setup_direction == "bull" and htf_trend == "bull":
        return True
    if setup_direction == "bear" and htf_trend == "bear":
        return True
    return False
