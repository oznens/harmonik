"""Miraz konseptleri ölçüm çekirdeği (saf) — fraktal/PaMonic/2-618 WR kıyası.

Canlı sisteme / Karakter skoruna DOKUNMAZ. CLI (miraz_olcum) gerçek veriyle
besler; bu modül yalnız toplama + raporlama yapar (test edilebilir).

Amaç: "harmonik + fraktal teyit" ve "harmonik + PaMonic" gerçekten WR'yi
yükseltiyor mu, 2-618 tek başına nasıl performe ediyor — sayıyla görmek.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from terminal.detection.two_618 import Pattern2618


@dataclass
class Bucket:
    """Bir strateji/filtre kovası — WR ve R toplamı."""
    name: str
    passed: int = 0        # filtreyi geçen setup
    tp: int = 0
    stop: int = 0
    other: int = 0         # EO/ZI/Aday/Aktif (işlem açılmadı/sonuçsuz)
    total_r: float = 0.0

    def add(self, outcome: str, r: float) -> None:
        self.passed += 1
        self.total_r += r
        if outcome == "TP":
            self.tp += 1
        elif outcome == "STOP":
            self.stop += 1
        else:
            self.other += 1

    @property
    def decided(self) -> int:
        return self.tp + self.stop

    @property
    def win_rate(self) -> float:
        return (self.tp / self.decided * 100) if self.decided else 0.0


@dataclass
class HarmonicRecord:
    """Tek harmonik setup'ın ölçüm verisi."""
    outcome: str           # TP/STOP/EO/...
    r: float               # trade_r ile hesaplanan R
    fraktal: bool          # fraktal teyit var mı (D'den sonra, karar anına dek)
    pamonic: bool          # OB@D (PaMonic) çakışması var mı


_HARMONIC_FILTERS: list[tuple[str, Callable[[HarmonicRecord], bool]]] = [
    ("Baz (tüm harmonik)", lambda r: True),
    ("+ Fraktal teyit",     lambda r: r.fraktal),
    ("+ PaMonic (OB@D)",    lambda r: r.pamonic),
    ("+ Fraktal & PaMonic", lambda r: r.fraktal and r.pamonic),
]


def harmonic_buckets(records: list[HarmonicRecord]) -> list[Bucket]:
    """Harmonik setupları filtre kovalarına göre topla (Baz / +fraktal / +PaMonic)."""
    out: list[Bucket] = []
    for name, pred in _HARMONIC_FILTERS:
        b = Bucket(name)
        for rec in records:
            if pred(rec):
                b.add(rec.outcome, rec.r)
        out.append(b)
    return out


def simulate_two_618(pat: Pattern2618, future: list[dict[str, Any]]) -> str:
    """2-618 yapısının outcome'u (limit giriş: 0.618'e pullback → stop/tp1).

    future: pattern'in 5. noktasından (d) SONRAKİ mumlar.
    bull: entry'ye iner (low<=entry) → girer; sonra stop (low<=stop) / tp1 (high>=tp1).
          tp1 girişten önce vurulursa hareket bizsiz oldu → EO.
    """
    bull = pat.direction == "bull"
    entry, stop, tp1 = pat.entry, pat.stop, pat.tp1
    filled = False
    for bar in future:
        if not filled:
            tp_first = (bull and bar["high"] >= tp1) or (not bull and bar["low"] <= tp1)
            touched = (bull and bar["low"] <= entry) or (not bull and bar["high"] >= entry)
            if touched:
                filled = True
                continue
            if tp_first:
                return "EO"          # 0.618'e gelmeden tp1'e gitti → kaçtı
        else:
            hit_sl = (bull and bar["low"] <= stop) or (not bull and bar["high"] >= stop)
            hit_tp = (bull and bar["high"] >= tp1) or (not bull and bar["low"] <= tp1)
            if hit_sl:
                return "STOP"
            if hit_tp:
                return "TP"
    return "Aktif" if filled else "EO"


def format_buckets(title: str, buckets: list[Bucket]) -> str:
    lines = [title,
             f"{'Strateji':<22}{'Setup':>7}{'Karar':>7}{'WR':>8}{'Top.R':>9}"]
    for b in buckets:
        lines.append(f"{b.name:<22}{b.passed:>7}{b.decided:>7}"
                     f"{b.win_rate:>7.1f}%{b.total_r:>9.1f}")
    return "\n".join(lines)
