"""Yüzde tabanlı ZigZag pivot dedektörü.

Son pivot'tan en az `threshold` kadar zıt yönde fiyat hareketi olduğunda
yeni pivot oluşur. Dönen liste kronolojik (eski → yeni) ve high/low
dönüşümlüdür. Çalışan (henüz onaylanmamış) son extremum da pivot olarak
döner — formasyonun D noktası genelde bu olur.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Pivot:
    """Bir swing high veya low.

    Attributes:
        index: kline listesindeki konum.
        time: ms cinsinden open_time (eşleştirme & DB için).
        price: pivot fiyatı (high veya low).
        kind: "high" veya "low".
    """
    index: int
    time: int
    price: float
    kind: str


def find_pivots(klines: list[dict[str, Any]], threshold: float) -> list[Pivot]:
    """Yüzde tabanlı ZigZag.

    Args:
        klines: open_time/high/low/close alanlı dict listesi (eski → yeni).
        threshold: pivot oluşması için gereken minimum yüzde hareket (örn. 0.02 = %2).

    Returns:
        Pivot listesi. high ve low pivotları dönüşümlüdür.
    """
    if len(klines) < 2 or threshold <= 0:
        return []

    pivots: list[Pivot] = []

    # Başlangıç durumu: ilk mumun close'unu referans al, yön bilinmiyor.
    first = klines[0]
    ext_idx = 0
    ext_price = first["close"]
    direction: str | None = None

    for i in range(1, len(klines)):
        k = klines[i]
        h = k["high"]
        l = k["low"]

        if direction == "up":
            # extremum'u (high) genişlet
            if h > ext_price:
                ext_idx = i
                ext_price = h
            # son high'tan threshold kadar geri çekildiyse → reversal
            elif (ext_price - l) / ext_price >= threshold:
                pivots.append(Pivot(ext_idx, klines[ext_idx]["open_time"], ext_price, "high"))
                ext_idx = i
                ext_price = l
                direction = "down"
        elif direction == "down":
            if l < ext_price:
                ext_idx = i
                ext_price = l
            elif (h - ext_price) / ext_price >= threshold:
                pivots.append(Pivot(ext_idx, klines[ext_idx]["open_time"], ext_price, "low"))
                ext_idx = i
                ext_price = h
                direction = "up"
        else:  # direction None — ilk yön
            move_up = (h - ext_price) / ext_price if ext_price > 0 else 0.0
            move_down = (ext_price - l) / ext_price if ext_price > 0 else 0.0
            if move_up >= threshold:
                # İlk pivot LOW (başlangıç noktası), şimdi up trendindeyiz.
                pivots.append(Pivot(0, first["open_time"], first["low"], "low"))
                ext_idx = i
                ext_price = h
                direction = "up"
            elif move_down >= threshold:
                pivots.append(Pivot(0, first["open_time"], first["high"], "high"))
                ext_idx = i
                ext_price = l
                direction = "down"

    # Son çalışan extremum'u da pivot olarak ekle — formasyon D noktası
    # genelde bu olur.
    if direction is not None:
        kind = "high" if direction == "up" else "low"
        pivots.append(Pivot(ext_idx, klines[ext_idx]["open_time"], ext_price, kind))

    # Aynı index'te iki pivot olamaz (initial'da olabiliyor); dedupla.
    deduped: list[Pivot] = []
    for p in pivots:
        if not deduped or deduped[-1].index != p.index:
            deduped.append(p)
    return deduped
