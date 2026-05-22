"""Formasyon dedektör çıktısı: Setup veri sınıfı."""
from __future__ import annotations

from dataclasses import dataclass

from terminal.detection.pivots import Pivot


@dataclass
class Setup:
    """Tespit edilen harmonik formasyon + işlem seviyeleri."""

    symbol: str
    interval: str
    pattern_name: str
    direction: str  # "bull" veya "bear"

    # 5 pivot: X, A, B, C, D
    pivots: dict[str, Pivot]

    # Oran ölçümleri
    b_ratio: float       # B'nin XA retracement'i
    c_ratio: float       # C'nin AB retracement'i
    d_ratio: float       # D'nin XA değeri
    bc_proj: float       # |CD|/|BC| BC projection
    cd_ab_ratio: float   # |CD|/|AB|
    ab_cd_equivalent: bool  # AB=CD veya 1.27/1.618 AB=CD eşleşmesi var mı

    # PRZ ve işlem seviyeleri
    prz_low: float
    prz_high: float
    prz_components: list[tuple[str, float]]  # ("0.786 XA", 104.28), ("AB=CD", 104.31), ...

    entry: float        # tanımlayıcı limit (D ideal fiyatı)
    stop: float
    tp1: float          # 0.382 IPO (formasyon uç noktalarından)
    tp2: float          # 0.618 IPO

    detected_at: int    # ms — taramanın çalıştığı an

    def summary(self) -> str:
        return (
            f"{self.direction.upper():4s} {self.pattern_name:14s} {self.symbol} {self.interval} "
            f"| PRZ {self.prz_low:.6g}-{self.prz_high:.6g} "
            f"| Entry {self.entry:.6g} SL {self.stop:.6g} "
            f"TP1 {self.tp1:.6g} TP2 {self.tp2:.6g} "
            f"| B={self.b_ratio:.3f} D={self.d_ratio:.3f}"
            f"{' AB=CD' if self.ab_cd_equivalent else ''}"
        )
