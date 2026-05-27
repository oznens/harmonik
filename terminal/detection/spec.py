"""XABCD formasyon parametreleri — config/pattern_rules.json'dan yüklenir.

Veri kaynağı: kullanıcının paylaştığı PDF (Trading Strategy Guides).
JSON yapısı pattern kurallarını koddan ayırarak güncelleme kolaylığı sağlar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PatternSpec:
    name: str

    # B noktası: XA retracement bandı
    b_min: float
    b_max: float

    # C noktası: AB retracement bandı (genelde 0.382-0.886, hepsinde aynı)
    c_min: float
    c_max: float

    # D noktası: XA değeri (retracement <1 veya extension >1)
    d_min: float
    d_max: float
    d_ideal: float

    # BC projeksiyonu (|CD|/|BC|) bandı
    bc_proj_min: float
    bc_proj_max: float

    # AB=CD onayı için kabul edilen CD/AB oran(lar)ı — biri D ile çakışırsa onay var
    ab_cd_target_ratios: tuple[float, ...]

    # Stop loss seviyesi (XA cinsi, A pivot'unun ötesinde)
    stop_at_xa: float


# C noktası tüm formasyonlarda 0.382-0.886 AB retracement aralığında
_C_MIN = 0.382
_C_MAX = 0.886

# AB=CD onayı için CD oranının hedefe yaklaşıklık toleransı (yüzde)
AB_CD_TOLERANCE = 0.10

# JSON config yolu (proje kökü/config/pattern_rules.json)
_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "pattern_rules.json"


def _load_patterns() -> dict[str, PatternSpec]:
    """JSON dosyasından XABCD pattern spec'lerini yükler.

    JSON'daki Cypher ve Shark farklı yapıya sahip (kendi pattern modülleri
    bu kuralları zaten içeriyor) — XABCD ailesi (B/D bandı + BC_proj olanlar)
    burada PatternSpec'e dönüşür.
    """
    raw = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    patterns: dict[str, PatternSpec] = {}
    for name, cfg in raw.items():
        if name.startswith("_"):  # meta alanları
            continue
        # XABCD pattern'i mi? B, C, D ve BC_proj alanları olmalı.
        if not (isinstance(cfg, dict) and "B" in cfg and "C" in cfg
                and "D" in cfg and "BC_proj" in cfg):
            continue  # Cypher / Shark XABCD spec'i kullanmıyor
        spec = PatternSpec(
            name=name,
            b_min=float(cfg["B"]["min"]),
            b_max=float(cfg["B"]["max"]),
            c_min=float(cfg["C"]["min"]),
            c_max=float(cfg["C"]["max"]),
            d_min=float(cfg["D"]["min"]),
            d_max=float(cfg["D"]["max"]),
            d_ideal=float(cfg["D"]["ideal"]),
            bc_proj_min=float(cfg["BC_proj"]["min"]),
            bc_proj_max=float(cfg["BC_proj"]["max"]),
            ab_cd_target_ratios=tuple(float(r) for r in cfg["ab_cd_target_ratios"]),
            stop_at_xa=float(cfg["stop_at_xa"]),
        )
        patterns[name] = spec
    return patterns


PATTERNS: dict[str, PatternSpec] = _load_patterns()
