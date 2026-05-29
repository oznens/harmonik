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
