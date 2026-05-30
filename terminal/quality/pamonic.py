"""PaMonic — Price Action + Harmonic confluence (tradermiraz konsepti).

tradermiraz (18 Nis 2026): "Harmoniklerin D bölgesinde neden Price Action
aramıyoruz? Özellikle Gartley D bölgesinde OrderBlock kullanıp pozisyonu ona
göre yönetmiyoruz?" → PaMonic = harmonik D'si bir Order Block ile çakışıyorsa
güçlü confluence. Kendi backtest'i: NADİR ama güçlü (ETH 2H 4 yapı %100 TP).

Order Block (emir bloğu): impulsif hareketten önceki son ters yönlü mum.
  bull (demand): bir düşüş mumunu, high'ını KAPANIŞLA aşan yükseliş mumu izler.
  bear (supply): bir yükseliş mumunu, low'unu kapanışla kıran düşüş izler.

Saf modül: tek dosya, klines + Setup alır, DB/ağ yok. Konsey/ICT framework YOK.
Bu YÖN elemez — yalnız confluence işareti (giriş kalitesi). Ölçüm sonra.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terminal.detection.models import Setup


@dataclass
class OrderBlock:
    kind: str           # "bull" (demand) | "bear" (supply)
    top: float
    bottom: float
    index: int
    time: int
    mitigated: bool     # fiyat sonradan bloğa geri döndü mü
    displacement: float # impuls mumunun gövde oranı (momentum)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def overlaps(self, lo: float, hi: float) -> bool:
        return not (hi < self.bottom or lo > self.top)


def find_order_blocks(klines: list[dict[str, Any]],
                      min_displacement: float = 0.0) -> list[OrderBlock]:
    """klines üzerinde tüm emir bloklarını bul (saf)."""
    out: list[OrderBlock] = []
    n = len(klines)
    for i in range(n - 1):
        cur, nxt = klines[i], klines[i + 1]
        # bull OB: düşüş mumu + sonraki yükseliş cur.high'ı kapanışla aşar
        if cur["close"] < cur["open"] and nxt["close"] > nxt["open"] \
                and nxt["close"] > cur["high"]:
            disp = (nxt["close"] - nxt["open"]) / nxt["open"] if nxt["open"] > 0 else 0.0
            if disp >= min_displacement:
                mitigated = any(klines[j]["low"] <= cur["high"] for j in range(i + 2, n))
                out.append(OrderBlock("bull", cur["high"], cur["low"], i,
                                      cur["open_time"], mitigated, disp))
        # bear OB: yükseliş mumu + sonraki düşüş cur.low'u kapanışla kırar
        elif cur["close"] > cur["open"] and nxt["close"] < nxt["open"] \
                and nxt["close"] < cur["low"]:
            disp = (nxt["open"] - nxt["close"]) / nxt["open"] if nxt["open"] > 0 else 0.0
            if disp >= min_displacement:
                mitigated = any(klines[j]["high"] >= cur["low"] for j in range(i + 2, n))
                out.append(OrderBlock("bear", cur["high"], cur["low"], i,
                                      cur["open_time"], mitigated, disp))
    return out


def pamonic_confluence(
    setup: Setup,
    klines: list[dict[str, Any]],
    min_displacement: float = 0.0,
) -> OrderBlock | None:
    """Harmonik D'nin (PRZ) bir Order Block ile çakışması — PaMonic.

    bull setup → PRZ ile çakışan bir BULL (demand) emir bloğu ara.
    bear setup → BEAR (supply) bloğu ara.

    Look-ahead: çağıran taraf klines'i KARAR anına (confirm/giriş) kadar keserek
    verir — OB'nin impulsu D'den sonra olur, confirm anında bilinir (sistemin
    geri kalanıyla aynı disiplin). Tercih: mitige olmamış + en yeni (D'ye yakın).

    Returns: çakışan blok, yoksa None.
    """
    obs = find_order_blocks(klines, min_displacement)
    want = setup.direction  # "bull" | "bear"
    cands = [o for o in obs
             if o.kind == want and o.overlaps(setup.prz_low, setup.prz_high)]
    if not cands:
        return None
    unmit = [o for o in cands if not o.mitigated]
    return max(unmit or cands, key=lambda o: o.index)
