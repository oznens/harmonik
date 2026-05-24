"""Formasyon dedektör çıktısı: Setup veri sınıfı."""
from __future__ import annotations

from dataclasses import dataclass, field

from terminal.detection.pivots import Pivot


@dataclass
class Setup:
    """Tespit edilen harmonik formasyon + işlem seviyeleri."""

    symbol: str
    interval: str
    pattern_name: str
    direction: str  # "bull" veya "bear"

    # 5 pivot: X, A, B, C, D (AB=CD için X = A duplikatı; Shark için X = "0", A = "X", ...)
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

    # Faz 4: Q skoru + HTF-LTF kontrol (varsayılan: hesaplanmamış)
    q_score: int = 0
    q_category: str = ""                              # "Riskli" | "Normal" | "Kaliteli" | ""
    q_components: dict[str, float] = field(default_factory=dict)
    htf_interval: str | None = None                   # eşleştirilen üst TF (örn. "4h")
    htf_trend: str | None = None                      # "bull" | "bear" | "neutral" | None
    htf_aligned: bool | None = None                   # True/False/None (neutral veya HTF yok)
    elenen: bool = False                              # HTF zıt yön → Elenen havuzu

    # Pattern ailesi: "xabcd" (Gartley/Bat/Crab/Butterfly), "abcd" (4-nokta),
    # "shark" (0-X-A-B-C), "five_zero" (X-A-B-C-D farklı kural),
    # "three_drives" (D1-R1-D2-R2-D3). UI/chart bu alana göre render eder.
    pattern_family: str = "xabcd"

    def summary(self) -> str:
        q_part = f" Q={self.q_score}" if self.q_score else ""
        cat_part = f" {self.q_category}" if self.q_category else ""
        elenen_part = " [ELENEN]" if self.elenen else ""
        return (
            f"{self.direction.upper():4s} {self.pattern_name:14s} {self.symbol} {self.interval}"
            f"{q_part}{cat_part}{elenen_part} "
            f"| PRZ {self.prz_low:.6g}-{self.prz_high:.6g} "
            f"| Entry {self.entry:.6g} SL {self.stop:.6g} "
            f"TP1 {self.tp1:.6g} TP2 {self.tp2:.6g} "
            f"| B={self.b_ratio:.3f} D={self.d_ratio:.3f}"
            f"{' AB=CD' if self.ab_cd_equivalent else ''}"
        )
