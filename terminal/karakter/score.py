"""Karakter skoru — bir (parite, TF, pattern, yön) için tarihsel başarı ölçütü.

Win rate = TP / (TP + STOP). Örneklem azsa skor güvenilirliği düşer.
Karakter skoru = WR × min(N/30, 1.0) × 100, burada N = TP+STOP.
"""
from __future__ import annotations

from dataclasses import dataclass


# Tam ağırlığa ulaşmak için gereken minimum örneklem (TP+STOP)
FULL_WEIGHT_SAMPLES = 30


def trade_r(entry: float, stop: float, tp1: float, outcome: str,
            cost_pct: float = 0.0) -> float:
    """R puanı: TP'de +R_potansiyeli, STOP'ta -1R, EO/ZI/Aday/Aktif'te 0.

    R potansiyeli = |TP1 - Entry| / |Entry - SL|

    Args:
        cost_pct: round-trip işlem maliyeti (komisyon + spread), entry'nin
            yüzdesi olarak. Default 0 (geriye uyumlu — saf teorik R).
            MEXC spot için ~0.0025 (komisyon %0.2 + spread %0.05) önerilir.
            Maliyet TP'de R'ı azaltır, STOP'ta R'ı büyütür (|R|>1).
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    cost = entry * cost_pct  # mutlak fiyat birimi
    if outcome == "TP":
        reward_net = abs(tp1 - entry) - cost
        return round(reward_net / risk, 4)
    if outcome == "STOP":
        loss_net = risk + cost
        return round(-loss_net / risk, 4)
    return 0.0


@dataclass
class KarakterStats:
    sample_count: int  # toplam setup (her durum)
    tp_count: int
    stop_count: int
    eo_count: int
    zi_count: int
    open_count: int    # hâlâ Aday veya Aktif
    win_rate: float    # TP / (TP+STOP), [0..1]; örneklem 0 ise 0
    karakter_score: float  # 0-100


def compute_stats(outcomes: list[str]) -> KarakterStats:
    """Outcome listesinden istatistik hesapla."""
    tp = sum(1 for o in outcomes if o == "TP")
    stop = sum(1 for o in outcomes if o == "STOP")
    eo = sum(1 for o in outcomes if o == "EO")
    zi = sum(1 for o in outcomes if o == "ZI")
    open_ = sum(1 for o in outcomes if o in ("Aday", "Aktif"))
    decided = tp + stop
    wr = (tp / decided) if decided > 0 else 0.0
    weight = min(decided / FULL_WEIGHT_SAMPLES, 1.0)
    karakter = wr * weight * 100
    return KarakterStats(
        sample_count=len(outcomes),
        tp_count=tp, stop_count=stop, eo_count=eo, zi_count=zi,
        open_count=open_,
        win_rate=round(wr, 4),
        karakter_score=round(karakter, 2),
    )
