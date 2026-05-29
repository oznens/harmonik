"""Market yapısı (swing) tespiti + CHoCH/MSB onayı — Price Action / SMC katmanı.

Yapısal filtre #3 (Price Action): harmonik D noktası oluştuktan sonra ALT zaman
diliminde (LTF) market yapısının trade yönüne döndüğünü doğrular (Change of
Character / Market Structure Break). "Düşen bıçağı tutma" mantığı — fiyat D'ye
gelse bile yön onaylanmadan girme. Bu, D noktasını delip geçen trendlerin
gereksiz stoplarını eler.

Saf fonksiyonlar; veri kaynağından bağımsız → backtest ve canlı AYNI mantığı
kullanır. Lookahead YOKTUR: her bar yalnızca o ana kadar onaylanmış swing'leri
görür (gerçek zamanlı karar ile birebir).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Swing:
    """Fractal swing high/low.

    Attributes:
        index: kline listesindeki konum.
        time: ms cinsinden open_time.
        price: swing fiyatı (high veya low).
        kind: "high" veya "low".
    """
    index: int
    time: int
    price: float
    kind: str


@dataclass(frozen=True)
class ChochResult:
    """CHoCH/MSB onay sonucu."""
    confirmed: bool
    broken_level: float | None = None   # kırılan swing seviyesi (lower high / higher low)
    confirm_idx: int | None = None      # onay barının indeksi (verilen klines içinde)
    confirm_time: int | None = None     # onay barının open_time'ı (ms)
    confirm_close: float | None = None  # onay barının kapanışı


def _is_swing_high(klines: list[dict[str, Any]], i: int, left: int, right: int) -> bool:
    """i barı swing high mı? high[i] çevresindeki left+right barın HEPSİNDEN kesin büyük."""
    hi = klines[i]["high"]
    for k in range(i - left, i):
        if klines[k]["high"] >= hi:
            return False
    for k in range(i + 1, i + right + 1):
        if klines[k]["high"] >= hi:
            return False
    return True


def _is_swing_low(klines: list[dict[str, Any]], i: int, left: int, right: int) -> bool:
    """i barı swing low mu? low[i] çevresindeki left+right barın HEPSİNDEN kesin küçük."""
    lo = klines[i]["low"]
    for k in range(i - left, i):
        if klines[k]["low"] <= lo:
            return False
    for k in range(i + 1, i + right + 1):
        if klines[k]["low"] <= lo:
            return False
    return True


def swing_points(
    klines: list[dict[str, Any]], left: int = 2, right: int = 2
) -> list[Swing]:
    """Fractal swing high/low listesi (kronolojik, eski→yeni).

    Bir bar swing high'tır: high'ı kendinden önceki `left` ve sonraki `right`
    barın hepsinden kesin büyükse. Swing low: low'u hepsinden kesin küçükse.
    Sadece left+right penceresi tam olan barlar (kenarlar atlanır).

    ZigZag (`detection/pivots.py`) yüzde-tabanlı trend pivotu bulurken bu fonksiyon
    mekanik fractal yapı noktalarını bulur — CHoCH, Order Block, likidite için.
    """
    n = len(klines)
    out: list[Swing] = []
    for i in range(left, n - right):
        if _is_swing_high(klines, i, left, right):
            out.append(Swing(i, klines[i]["open_time"], klines[i]["high"], "high"))
        elif _is_swing_low(klines, i, left, right):
            out.append(Swing(i, klines[i]["open_time"], klines[i]["low"], "low"))
    return out


def check_choch(
    klines: list[dict[str, Any]],
    side: str,
    left: int = 2,
    right: int = 2,
    max_bars: int | None = None,
) -> ChochResult:
    """Alt zaman diliminde market yapısı kırılımı (CHoCH/MSB) onayı ara.

    Bull (D=dip): düşüşte sürekli "lower high" yapılır. En son ONAYLANMIŞ swing
    high bir bar KAPANIŞIYLA yukarı kırılırsa → karakter değişti (CHoCH), onay.
    Bear (D=tepe): en son swing low bir bar kapanışıyla aşağı kırılırsa onay.

    Lookahead YOK: bar j'de yalnızca sağ-penceresi j'de tamamlanan (i = j-right)
    swing'ler bilinir. Bir swing onaylandığı barda zaten kırılamaz (tanımı gereği
    o barın high/low'u swing'i geçemez), bu yüzden yapay erken tetik oluşmaz.

    Args:
        klines: ALT TF mum dizisi (eski→yeni); genelde D pivotundan SONRAsı.
        side: "bull"/"BUY" veya "bear"/"SELL".
        left/right: fractal swing penceresi (varsayılan 2/2 — kullanıcı mantığı).
        max_bars: bu kadar bar içinde onay yoksa confirmed=False. None = tümü.

    Returns:
        ChochResult — onay varsa kırılan seviye + onay barı bilgisi.
    """
    bull = side.lower() in ("bull", "buy")
    n = len(klines)
    limit = n if max_bars is None else min(n, max_bars)
    last_level: float | None = None  # bull: son swing high; bear: son swing low

    for j in range(limit):
        # Sağ penceresi tam bu barda kapanan swing: i = j - right.
        i = j - right
        if i - left >= 0:
            if bull:
                if _is_swing_high(klines, i, left, right):
                    last_level = klines[i]["high"]
            else:
                if _is_swing_low(klines, i, left, right):
                    last_level = klines[i]["low"]
        # CHoCH testi: bar j kapanışı son yapı seviyesini kırdı mı?
        if last_level is not None:
            c = klines[j]["close"]
            if (bull and c > last_level) or (not bull and c < last_level):
                return ChochResult(
                    confirmed=True, broken_level=last_level, confirm_idx=j,
                    confirm_time=klines[j]["open_time"], confirm_close=c,
                )
    return ChochResult(confirmed=False)


# ─────────────────────────────────────────────────────────────────────────────
# Price Action / SMC bölge detektörleri (#4 Order Block · #5 FVG · #6 Sweep)
# Hepsi aynı zaman diliminde, D pivotunun SOLUNDAKİ mumlarla çalışır — yeni veri
# altyapısı gerektirmez. {"type": "bull"/"bear", "top", "bottom", "index"} döner.
# ─────────────────────────────────────────────────────────────────────────────


def find_fair_value_gaps(
    klines: list[dict[str, Any]], lookback: int | None = None
) -> list[dict[str, Any]]:
    """Fair Value Gap (FVG / Imbalance) bölgeleri — ardışık 3 mumda fiyat boşluğu.

    Bull FVG: 1. mumun high'ı 3. mumun low'undan KÜÇÜK (arada boşluk) →
      bottom=high[i-1], top=low[i+1]. Bear FVG: 1. mumun low'u 3. mumun
      high'ından BÜYÜK → top=low[i-1], bottom=high[i+1]. i = ortadaki mum.

    Fiyat bu verimsiz boşlukları "doldurma" eğilimindedir (mıknatıs). Harmonik
    D noktası dolmamış bir FVG'nin içine denk geliyorsa dönüş ihtimali artar.
    """
    out: list[dict[str, Any]] = []
    n = len(klines)
    start = 1 if lookback is None else max(1, n - lookback)
    for i in range(start, n - 1):
        prev, nxt = klines[i - 1], klines[i + 1]
        if prev["high"] < nxt["low"]:
            out.append({"type": "bull", "bottom": prev["high"],
                        "top": nxt["low"], "index": i})
        elif prev["low"] > nxt["high"]:
            out.append({"type": "bear", "top": prev["low"],
                        "bottom": nxt["high"], "index": i})
    return out


def find_order_blocks(
    klines: list[dict[str, Any]],
    displacement: int = 3,
    lookback: int | None = None,
) -> list[dict[str, Any]]:
    """Order Block (kurumsal emir bloğu) bölgeleri.

    Bull OB: sert bir yükselişten ÖNCEKİ son DÜŞÜŞ (kırmızı) mumu. Kural:
      kırmızı mum (close<open) + sonraki `displacement` mum içinde fiyat o mumun
      HIGH'ını kapanışla yukarı kırar (displacement/BOS) ve net yükseliş var →
      kutu = [low, high]. Bear OB: yeşil mum + sonraki mumlarda low aşağı kırılır.

    Harmonik D noktası geçmiş bir OB ile çakışıyorsa = "Fibonacci + kurumsal
    bölge" kesişimi → güçlü.
    """
    out: list[dict[str, Any]] = []
    n = len(klines)
    start = 0 if lookback is None else max(0, n - lookback)
    for i in range(start, n - displacement):
        o, c = klines[i]["open"], klines[i]["close"]
        hi, lo = klines[i]["high"], klines[i]["low"]
        nxt = klines[i + 1: i + 1 + displacement]
        if c < o:  # kırmızı → bull OB adayı
            broke = any(b["close"] > hi for b in nxt)
            ups = sum(1 for b in nxt if b["close"] > b["open"])
            if broke and ups >= 1:
                out.append({"type": "bull", "top": hi, "bottom": lo, "index": i})
        elif c > o:  # yeşil → bear OB adayı
            broke = any(b["close"] < lo for b in nxt)
            downs = sum(1 for b in nxt if b["close"] < b["open"])
            if broke and downs >= 1:
                out.append({"type": "bear", "top": hi, "bottom": lo, "index": i})
    return out


def check_liquidity_sweep(
    klines: list[dict[str, Any]],
    d_index: int,
    side: str,
    lookback: int = 50,
) -> bool:
    """D barında likidite alımı (stop avı / sweep) oldu mu?

    Bull: D barı, soldaki en yakın belirgin dibin (old_low) ALTINA iğne atar
    ama gövdeyi (close) o dibin ÜZERİNDE kapatır → aşağıdaki stoplar patlatıldı,
    fiyat geri toplandı (en güçlü dönüş sinyali). Bear: old_high üstüne iğne,
    altında kapanış.
    """
    bull = side.lower() in ("bull", "buy")
    if d_index <= 0 or d_index >= len(klines):
        return False
    lo = max(0, d_index - lookback)
    hist = klines[lo:d_index]
    if not hist:
        return False
    d = klines[d_index]
    if bull:
        old_low = min(k["low"] for k in hist)
        return d["low"] < old_low and d["close"] > old_low
    old_high = max(k["high"] for k in hist)
    return d["high"] > old_high and d["close"] < old_high
