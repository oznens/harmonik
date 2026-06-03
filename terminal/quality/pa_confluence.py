"""PA confluence — Order Block'a EK price-action sinyalleri (SMC).

İnternet kaynaklarından öğrenilen, en çok kanıtlanmış "Confirmation Model"
(OB + FVG + Liquidity Sweep) + premium/discount(OTE) + rejection candle.
Bizim sistemimizle harman: harmonik D bölgesinde OB zaten var (pamonic.py);
bu modül o D bölgesinde EK PA confluence'ı ölçer → giriş KALİTE filtresi.

Saf modül: klines + Setup + d_index alır, DB/ağ yok, yön elemez.
Tüm fonksiyonlar look-ahead'siz: yalnız d_index ve öncesine bakar (karar anı).

Kaynaklar (özet):
  - Likidite süpürme: fitil önceki swing'i deler, gövde içeride kapanır (rejection).
  - FVG: 3-mum dengesizliği (boğa: c3.low > c1.high), D/PRZ bölgesiyle çakışırsa güç.
  - Premium/Discount: boğa girişi discount'ta (eq altı), OTE 0.62-0.79 retrace.
  - Rejection candle: D barında uzun ters-yön fitil.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from terminal.detection.models import Setup


@dataclass
class PASignals:
    """D bölgesindeki PA confluence sinyalleri (OB'ye ek)."""
    liq_sweep: bool = False       # D, önceki swing likiditesini süpürüp geri kapandı
    fvg: bool = False             # D/PRZ ile çakışan Fair Value Gap var
    discount: bool = False        # giriş doğru yarıda (boğa=discount / ayı=premium)
    ote: bool = False             # giriş OTE bölgesinde (0.62-0.79 retrace)
    rejection: bool = False       # D barında uzun ters-yön fitil
    sweep_depth: float = 0.0      # süpürme derinliği (oran)
    retr: float = 0.0             # dealing-range retracement oranı
    components: dict[str, float] = field(default_factory=dict)

    @property
    def score(self) -> int:
        """0-5 confluence sayacı (OB hariç; OB zaten ön-şart)."""
        return int(self.liq_sweep) + int(self.fvg) + int(self.discount) \
            + int(self.ote) + int(self.rejection)


def _recent_swing(klines: list[dict[str, Any]], end_idx: int, kind: str,
                  lookback: int = 25, fractal: int = 2) -> float | None:
    """end_idx'ten ÖNCE en yakın fraktal swing (low/high) fiyatı.

    fractal=2 → bir bar, solundaki ve sağındaki 2'şer bardan daha ekstrem ise swing.
    """
    lo = max(fractal, end_idx - lookback)
    found: float | None = None
    for i in range(end_idx - 1, lo - 1, -1):
        if i - fractal < 0 or i + fractal >= len(klines):
            continue
        win = klines[i - fractal:i + fractal + 1]
        if kind == "low":
            if klines[i]["low"] == min(b["low"] for b in win):
                found = klines[i]["low"]; break
        else:
            if klines[i]["high"] == max(b["high"] for b in win):
                found = klines[i]["high"]; break
    return found


def liquidity_sweep(klines: list[dict[str, Any]], d_index: int, direction: str,
                    lookback: int = 25) -> tuple[bool, float]:
    """D, önceki swing likiditesini süpürdü mü (fitil deldi, gövde içeride kapandı)?

    boğa (D=dip): D barı low'u önceki swing low'un ALTINA indi ama close Üstünde.
    ayı  (D=tepe): D barı high'ı önceki swing high'ın Üstüne çıktı ama close ALtında.
    Süpürme + geri-kapanış = klasik smart-money stop avı imzası.
    """
    if d_index < 0 or d_index >= len(klines):
        return False, 0.0
    bar = klines[d_index]
    if direction == "bull":
        lvl = _recent_swing(klines, d_index, "low", lookback)
        if lvl is None or lvl <= 0:
            return False, 0.0
        if bar["low"] < lvl and bar["close"] > lvl:
            return True, (lvl - bar["low"]) / lvl
    else:
        lvl = _recent_swing(klines, d_index, "high", lookback)
        if lvl is None or lvl <= 0:
            return False, 0.0
        if bar["high"] > lvl and bar["close"] < lvl:
            return True, (bar["high"] - lvl) / lvl
    return False, 0.0


def fvg_confluence(klines: list[dict[str, Any]], d_index: int, direction: str,
                   prz_low: float, prz_high: float, near: int = 12) -> bool:
    """D çevresinde, PRZ ile çakışan Fair Value Gap (3-mum dengesizliği) var mı?

    boğa FVG: c3.low > c1.high → gap [c1.high, c3.low].
    ayı  FVG: c3.high < c1.low → gap [c3.high, c1.low].
    """
    n = len(klines)
    a = max(1, d_index - near)
    b = min(n - 1, d_index + near)
    for i in range(a, b):
        c1, c3 = klines[i - 1], klines[i + 1]
        if direction == "bull":
            if c3["low"] > c1["high"]:
                glo, ghi = c1["high"], c3["low"]
                if not (ghi < prz_low or glo > prz_high):
                    return True
        else:
            if c3["high"] < c1["low"]:
                glo, ghi = c3["high"], c1["low"]
                if not (ghi < prz_low or glo > prz_high):
                    return True
    return False


def premium_discount(klines: list[dict[str, Any]], d_index: int, entry: float,
                     direction: str, lookback: int = 50) -> tuple[bool, bool, float]:
    """Giriş, dealing-range'in doğru yarısında mı (boğa=discount/ayı=premium)?
    OTE: 0.62-0.79 retracement bölgesi. Döner: (discount_ok, ote, retr)."""
    seg = klines[max(0, d_index - lookback):d_index + 1]
    if not seg:
        return False, False, 0.0
    hi = max(b["high"] for b in seg)
    lo = min(b["low"] for b in seg)
    if hi <= lo:
        return False, False, 0.0
    eq = (hi + lo) / 2.0
    if direction == "bull":
        retr = (hi - entry) / (hi - lo)        # tepeden ne kadar geri (1=dip)
        return (entry <= eq), (0.62 <= retr <= 0.95), retr
    else:
        retr = (entry - lo) / (hi - lo)         # dipten ne kadar yukarı (1=tepe)
        return (entry >= eq), (0.62 <= retr <= 0.95), retr


def rejection_candle(klines: list[dict[str, Any]], d_index: int, direction: str,
                     min_wick: float = 0.5) -> bool:
    """D barında güçlü ters-yön reddi (uzun fitil)?
    boğa: alt fitil ≥ min_wick × bar aralığı. ayı: üst fitil."""
    if d_index < 0 or d_index >= len(klines):
        return False
    b = klines[d_index]
    rng = b["high"] - b["low"]
    if rng <= 0:
        return False
    body_lo = min(b["open"], b["close"])
    body_hi = max(b["open"], b["close"])
    if direction == "bull":
        return (body_lo - b["low"]) / rng >= min_wick
    return (b["high"] - body_hi) / rng >= min_wick


def pa_signals(setup: Setup, klines: list[dict[str, Any]], d_index: int) -> PASignals:
    """D bölgesindeki tüm PA confluence sinyallerini hesapla (OB'ye ek)."""
    direction = setup.direction
    sw, depth = liquidity_sweep(klines, d_index, direction)
    fvg = fvg_confluence(klines, d_index, direction, setup.prz_low, setup.prz_high)
    disc, ote, retr = premium_discount(klines, d_index, setup.entry, direction)
    rej = rejection_candle(klines, d_index, direction)
    sig = PASignals(liq_sweep=sw, fvg=fvg, discount=disc, ote=ote, rejection=rej,
                    sweep_depth=depth, retr=retr)
    sig.components = {"liq_sweep": float(sw), "fvg": float(fvg), "discount": float(disc),
                      "ote": float(ote), "rejection": float(rej)}
    return sig
