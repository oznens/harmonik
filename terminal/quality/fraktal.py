"""Fraktal (swing-pivot) yapı analizi — tradermiraz'ın "fraktal" kavramı.

tradermiraz "pivot" yerine "fraktal" der (kendi itirafı: "Pivot → Fraktal").
Fraktal yapı = swing high/low dizisi. Kullanımı:
  - Fraktal yapı etiketi: HH/HL/LH/LL.
  - Fraktal teyidi: "fraktal üstü kapanış" = yukarı kırılım, "fraktal altı
    kapanış" = aşağı. Harmonik D'den sonra dönüşün bir fraktal kırılımıyla
    teyit edilmesi (düşen bıçağı tutmamak) → giriş KALİTESİ.

ÖNEMLİ — bu YÖN filtresi DEĞİL: hem bu projenin backtest'i (score.py notu) hem
tradermiraz (29 May / Elenen gözlemi) trend-tersi harmoniklerin de iyi çalıştığını
buldu. Bu modül yönü elemez; yalnız GİRİŞ TEYİDİ/zamanlaması içindir.

Mevcut "confirm" entry modundan farkı: o önceki BARIN ekstremini kırınca onaylar
(gürültülü); bu, son swing FRAKTALININ kapanışla kırılmasını ister (daha sağlam).

Saf modül: klines/pivots alır, DB/ağ yok.
"""
from __future__ import annotations

from typing import Any

from terminal.detection.pivots import Pivot, find_pivots

# Fraktal (zigzag) tespiti için varsayılan eşik — TF'den bağımsız, küçük.
DEFAULT_FRAKTAL_THRESHOLD = 0.004


def swing_labels(pivots: list[Pivot]) -> list[tuple[Pivot, str]]:
    """Her fraktalı önceki AYNI TÜR fraktala göre etiketle (HH/HL/LH/LL).

    high → "HH" (higher high) / "LH" (lower high)
    low  → "HL" (higher low)  / "LL" (lower low); ilk → "H"/"L".
    """
    out: list[tuple[Pivot, str]] = []
    last_high: float | None = None
    last_low: float | None = None
    for p in pivots:
        if p.kind == "high":
            lbl = "H" if last_high is None else ("HH" if p.price > last_high else "LH")
            last_high = p.price
        else:
            lbl = "L" if last_low is None else ("HL" if p.price > last_low else "LL")
            last_low = p.price
        out.append((p, lbl))
    return out


def fraktal_trend(pivots: list[Pivot]) -> str:
    """Son fraktal yapısından trend: HH+HL = 'bull', LH+LL = 'bear', yoksa 'neutral'.

    (Bilgi amaçlı — yön ELEMEZ; tradermiraz trend-tersi harmonikleri de alıyor.)
    """
    labels = swing_labels(pivots)
    last_high = next((lbl for p, lbl in reversed(labels) if p.kind == "high"), None)
    last_low = next((lbl for p, lbl in reversed(labels) if p.kind == "low"), None)
    if last_high == "HH" and last_low == "HL":
        return "bull"
    if last_high == "LH" and last_low == "LL":
        return "bear"
    return "neutral"


def fraktal_confirm(
    klines: list[dict[str, Any]],
    direction: str,
    since_time: int | None = None,
    threshold: float = 0.0,
    min_bars: int = 8,
) -> bool:
    """D'den sonra fraktal teyidi var mı? (kapanış teyitli — fitil değil)

    bull → since_time sonrası son swing HIGH fraktalının ÜZERİNDE bir kapanış.
    bear → son swing LOW fraktalının ALTINDA bir kapanış.

    Args:
        klines: mum dizisi (eski→yeni).
        direction: "bull" | "bear" (harmonik yönü).
        since_time: D pivot zamanı (ms); bu andan sonraki barlara bak. None=hepsi.
        threshold: fraktal (zigzag) eşiği. 0 → varsayılan.
        min_bars: bu sayıdan az bar varsa teyit yok (veri yetersiz).
    """
    bars = klines if since_time is None else [k for k in klines if k["open_time"] >= since_time]
    if len(bars) < min_bars:
        return False
    thr = threshold if threshold > 0 else DEFAULT_FRAKTAL_THRESHOLD
    pivots = find_pivots(bars, thr)
    last_close = bars[-1]["close"]

    if direction == "bull":
        ref = next((p for p in reversed(pivots)
                    if p.kind == "high" and p.index < len(bars) - 1), None)
        return ref is not None and last_close > ref.price
    ref = next((p for p in reversed(pivots)
                if p.kind == "low" and p.index < len(bars) - 1), None)
    return ref is not None and last_close < ref.price


def fraktal_break_index(
    klines: list[dict[str, Any]],
    direction: str,
    threshold: float = 0.0,
) -> int | None:
    """Fraktal kırılımının (kapanışla) İLK gerçekleştiği bar indeksi. None=yok.

    Backtest giriş zamanlaması için: bu bardan SONRA girilir.
    """
    if len(klines) < 2:
        return None
    thr = threshold if threshold > 0 else DEFAULT_FRAKTAL_THRESHOLD
    pivots = find_pivots(klines, thr)
    bull = direction == "bull"
    for i in range(1, len(klines)):
        # i. bardan ÖNCE oluşmuş son uygun fraktal
        ref = next((p for p in reversed(pivots)
                    if p.kind == ("high" if bull else "low") and p.index < i), None)
        if ref is None:
            continue
        close = klines[i]["close"]
        if (bull and close > ref.price) or (not bull and close < ref.price):
            return i
    return None


def simulate_fraktal_entry(
    future: list[dict[str, Any]],
    direction: str,
    tp1: float,
    threshold: float = 0.0,
) -> tuple[str, float | None, float | None]:
    """Fraktal teyitli GECİKMELİ giriş + YAPISAL stop (tradermiraz tarzı).

    Fraktal kırılımını bekler (fraktal_break_index), kırılım barının SONRAKİ
    barının açılışından girer (market). Stop = kırılımdan ÖNCEKİ yapısal uç
    (bull: o ana kadarki en düşük low; bear: en yüksek high) — geniş PRZ stop'u
    değil, yapı bazlı tight stop. Sonra stop/tp1 (önce STOP).

    Returns: (outcome, actual_entry, stop). entry/stop None = giriş olmadı (EO).
    """
    bi = fraktal_break_index(future, direction, threshold)
    if bi is None or bi + 1 >= len(future):
        return ("EO", None, None)
    bull = direction == "bull"
    pre = future[: bi + 1]
    stop = min(b["low"] for b in pre) if bull else max(b["high"] for b in pre)
    actual = future[bi + 1]["open"]
    for j in range(bi + 1, len(future)):
        bar = future[j]
        hit_sl = (bull and bar["low"] <= stop) or (not bull and bar["high"] >= stop)
        hit_tp = (bull and bar["high"] >= tp1) or (not bull and bar["low"] <= tp1)
        if hit_sl:
            return ("STOP", actual, stop)
        if hit_tp:
            return ("TP", actual, stop)
    return ("Aktif", actual, stop)
