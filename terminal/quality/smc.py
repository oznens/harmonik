"""SMC bölge skoru — harmonik D noktasını kurumsal bölgelerle çakıştırma.

Yapısal filtre #4-6 (Price Action / Smart Money Concepts). Harmonik D noktası
sadece Fibonacci'ye değil, kurumsal iz bölgelerine de denk geliyorsa dönüş
ihtimali artar. Üç bağımsız sinyal birleştirilir (0-100):

  - Order Block      (40 puan): D, geçmiş bir OB kutusunun içinde mi
  - FVG / Imbalance  (30 puan): D, dolmamış bir fiyat boşluğunda mı
  - Liquidity Sweep  (30 puan): D barı soldaki dip/tepenin likiditesini avladı mı

Yol haritası mantığı "EN AZ BİRİ" → --min-smc 30 = en az bir bölge onayı.
Confluence (RSI+hacim) ile aynı kalıp: scanner _apply_smc ile setup'a yazar,
canlıda --min-smc kapısı, backtest'te format_smc_sweep taraması.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terminal.detection.structure import (
    check_liquidity_sweep,
    find_fair_value_gaps,
    find_order_blocks,
)

OB_PTS = 40.0
FVG_PTS = 30.0
SWEEP_PTS = 30.0


@dataclass
class SmcResult:
    score: int                    # 0-100
    components: dict[str, float]  # {order_block, fvg, sweep}
    order_block: bool
    fvg: bool
    sweep: bool


def compute_smc(
    setup: Any,
    klines: list[dict[str, Any]],
    ob_lookback: int = 150,
    fvg_lookback: int = 150,
    sweep_lookback: int = 50,
) -> SmcResult:
    """Setup'ın D noktası için SMC bölge skorunu hesapla. klines D pivot dahil.

    Yön-uyumlu (bull setup → bull OB/FVG) ve D'den ÖNCE oluşmuş bölgeler dikkate
    alınır. D fiyatı = D pivot fiyatı (bull: dip, bear: tepe).
    """
    components = {"order_block": 0.0, "fvg": 0.0, "sweep": 0.0}
    d_pivot = setup.pivots.get("D")
    if d_pivot is None:
        return SmcResult(0, components, False, False, False)
    d_time = d_pivot.time
    d_idx = next((i for i, k in enumerate(klines) if k["open_time"] == d_time), None)
    if d_idx is None:
        return SmcResult(0, components, False, False, False)

    side = setup.direction  # "bull" | "bear"
    d_price = d_pivot.price
    left = klines[: d_idx + 1]  # D ve öncesi (zonlar D'den önce oluşmuş olmalı)

    obs = find_order_blocks(left, lookback=ob_lookback)
    ob_hit = any(
        z["type"] == side and z["index"] < d_idx
        and z["bottom"] <= d_price <= z["top"]
        for z in obs
    )
    fvgs = find_fair_value_gaps(left, lookback=fvg_lookback)
    fvg_hit = any(
        z["type"] == side and z["index"] < d_idx
        and z["bottom"] <= d_price <= z["top"]
        for z in fvgs
    )
    sweep_hit = check_liquidity_sweep(klines, d_idx, side, lookback=sweep_lookback)

    if ob_hit:
        components["order_block"] = OB_PTS
    if fvg_hit:
        components["fvg"] = FVG_PTS
    if sweep_hit:
        components["sweep"] = SWEEP_PTS

    score = int(round(sum(components.values())))
    return SmcResult(
        score=max(0, min(100, score)),
        components={k: round(v, 1) for k, v in components.items()},
        order_block=ob_hit, fvg=fvg_hit, sweep=sweep_hit,
    )
