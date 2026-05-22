"""Karakter skoru — bir (parite, TF, pattern, yön) için tarihsel başarı ölçütü.

Win rate = TP / (TP + STOP). Örneklem azsa skor güvenilirliği düşer.
Karakter skoru = WR × min(N/30, 1.0) × 100, burada N = TP+STOP.
"""
from __future__ import annotations

from dataclasses import dataclass


# Tam ağırlığa ulaşmak için gereken minimum örneklem (TP+STOP)
FULL_WEIGHT_SAMPLES = 30


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
