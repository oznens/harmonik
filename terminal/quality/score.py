"""Q (Quality) skoru hesaplayıcı — 0-100 arası pattern-içsel kalite ölçütü.

Bileşenler (toplam 100):
  - PRZ density (30): PRZ bileşenlerinin ne kadar dar bir bantta toplandığı.
  - B precision (15): B noktasının formasyon bandının merkezine yakınlığı.
  - D precision (30): D noktasının tanımlayıcı ideal'e yakınlığı (en kritik).
  - AB=CD bonus (15): AB=CD onayı varsa tam puan.
  - BC projection (10): BC band içindeyse tam puan.

HTF alignment artık Q'dan çıkarıldı — backtest verisi (3 ay × 5 parite × 3 TF)
harmonik mean-reversion setuplarının HTF zıt'ta daha iyi performe ettiğini
gösteriyor (uyumlu +11R vs zıt +18R). HTF bilgisi setup.htf_aligned alanında
bağımsız flag olarak kalır; live tracker pattern-spesifik elenen mantığını
HTF_OPPOSITE_PENALIZED listesiyle uygular.

Kategori:
  Riskli   < 50
  Normal   50-69
  Kaliteli ≥ 70
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.detection.models import Setup
from terminal.detection.spec import PATTERNS


# Bileşen ağırlıkları (toplam 100) — HTF bileşeni çıkarıldı, 15 puanı dağıtıldı.
W_PRZ = 30.0  # +5 (PRZ density'nin önemini artır)
W_B = 15.0
W_D = 30.0   # +5 (D noktası harmonik patternin tanımlayıcı limit'i, en kritik)
W_ABCD = 15.0
W_BC = 10.0  # +5


@dataclass
class QualityResult:
    score: int
    category: str
    components: dict[str, float]  # her bileşenin aldığı puan


def _prz_density(setup: Setup) -> float:
    """PRZ bileşenlerinin yakınsama darlığı + sayısı.

    Dar bant + çok bileşen = yüksek puan.
    """
    components = setup.prz_components
    if len(components) < 2:
        return 0.0
    prices = [p for _, p in components]
    spread = max(prices) - min(prices)
    mean = sum(prices) / len(prices)
    if mean <= 0:
        return 0.0
    pct = spread / mean
    # %0.5'ten dar → tam puan, %2'den geniş → 0 puan (linear ara)
    if pct <= 0.005:
        tightness = 1.0
    elif pct >= 0.02:
        tightness = 0.0
    else:
        tightness = 1 - (pct - 0.005) / (0.02 - 0.005)
    # bileşen sayısı bonusu: 5+ bileşen = tam
    count_factor = min(len(components) / 5, 1.0)
    # 70% darlık, 30% sayı
    return W_PRZ * (0.7 * tightness + 0.3 * count_factor)


def _b_precision(setup: Setup) -> float:
    if setup.pattern_family != "xabcd":
        # AB=CD / Shark / 5-0 / Three Drives — B kavramı farklı, neutral puan
        return W_B * 0.5
    spec = PATTERNS.get(setup.pattern_name)
    if spec is None:
        return W_B * 0.5
    band_center = (spec.b_min + spec.b_max) / 2
    band_radius = (spec.b_max - spec.b_min) / 2
    if band_radius <= 0:
        return W_B
    distance = abs(setup.b_ratio - band_center) / band_radius
    return W_B * max(0.0, 1 - 0.5 * distance)


def _d_precision(setup: Setup) -> float:
    if setup.pattern_family != "xabcd":
        # AB=CD vs için: D'nin standart orana yakınlığı
        # d_ratio matched_ratio'yu tutuyor; her zaman tam puan (eşleşme zaten doğrulanmış)
        return W_D * 0.8
    spec = PATTERNS.get(setup.pattern_name)
    if spec is None:
        return W_D * 0.5
    half_width = max(spec.d_ideal - spec.d_min, spec.d_max - spec.d_ideal)
    if half_width <= 0:
        return W_D
    distance = abs(setup.d_ratio - spec.d_ideal)
    normalized = distance / half_width
    return W_D * max(0.0, 1 - 0.5 * normalized)


def _ab_cd(setup: Setup) -> float:
    return W_ABCD if setup.ab_cd_equivalent else 0.0


def _bc_proj(setup: Setup) -> float:
    if setup.pattern_family != "xabcd":
        return W_BC * 0.5  # AB=CD vs için BC kavramı farklı
    spec = PATTERNS.get(setup.pattern_name)
    if spec is None:
        return 0.0
    if spec.bc_proj_min <= setup.bc_proj <= spec.bc_proj_max:
        return W_BC
    return 0.0


def categorize(score: int) -> str:
    if score >= 70:
        return "Kaliteli"
    if score >= 50:
        return "Normal"
    return "Riskli"


def compute_q(setup: Setup, htf_trend: str | None = None) -> QualityResult:
    """Setup için Q skorunu, kategoriyi ve bileşen dökümünü hesapla.

    htf_trend parametresi geriye uyumluluk için duruyor ama Q hesabında
    kullanılmıyor — HTF kontrolü scanner._is_elenen ile ayrı yapılır.
    """
    components = {
        "prz_density": round(_prz_density(setup), 2),
        "b_precision": round(_b_precision(setup), 2),
        "d_precision": round(_d_precision(setup), 2),
        "ab_cd":       round(_ab_cd(setup), 2),
        "bc_proj":     round(_bc_proj(setup), 2),
    }
    total = round(sum(components.values()))
    score = min(100, max(0, total))
    return QualityResult(score=score, category=categorize(score), components=components)
