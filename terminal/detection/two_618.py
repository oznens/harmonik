"""2-618 Stratejisi — Çift Dip/Tepe + 0.618 giriş (tradermiraz / @finansalTRader).

Kullanıcının tarifi (görselli):
  "Çift dipten lokal tepeye, yani 4'ten 5'e fibo çek; 618 seviyesinde giriş.
   4 altı kapanışta stoplanır. İlk hedef 5; 2. hedef fib uzama 0.272."

Boğa (çift dip) yapı — 4 ardışık fraktal [a,b,c,d] = noktalar [2,3,4,5]:
  a(2)=dip, b(3)=ara tepe (neckline), c(4)=ikinci dip (a≈c → çift dip),
  d(5)=b'yi AŞAN lokal tepe (neckline kırılımı = onay).
  • Giriş  = 4→5 bacağının 0.618 retracement'i (5'ten geri çekilme)
  • Stop   = 4 seviyesi (altı kapanışta)
  • Hedef1 = 5 ; Hedef2 = 1.272 uzama (5 + 0.272×bacak)
Ayı (çift tepe) bunun aynasıdır.

Saf modül: pivot listesi (fraktal) alır, Pattern2618 listesi döner. DB/ağ yok.
Henüz canlı tarayıcıya bağlı DEĞİL — ölçüm sonra.
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.detection.pivots import Pivot, find_pivots

FIB_ENTRY = 0.618   # giriş retracement seviyesi
FIB_EXT = 0.272     # 2. hedef: 1.272 uzama (bacağın %27.2'si kadar 5'in ötesi)
DEFAULT_EQ_TOL = 0.03   # çift dip/tepe "eşit" toleransı (%3)


@dataclass
class Pattern2618:
    """Tespit edilen 2-618 yapısı + işlem seviyeleri."""
    direction: str                      # "bull" (çift dip) | "bear" (çift tepe)
    points: tuple[Pivot, Pivot, Pivot, Pivot]   # (2, 3, 4, 5)
    entry: float                        # 0.618 retracement
    stop: float                         # 4 seviyesi
    tp1: float                          # 5 seviyesi
    tp2: float                          # 1.272 uzama

    @property
    def rr(self) -> float:
        """Hedef1'e R:R — geometriden ~1.618 çıkar (0.618/0.382)."""
        risk = abs(self.entry - self.stop)
        return abs(self.tp1 - self.entry) / risk if risk > 0 else 0.0


def find_two_618(pivots: list[Pivot], eq_tol: float = DEFAULT_EQ_TOL) -> list[Pattern2618]:
    """Ardışık 4 fraktal pencerelerinde 2-618 yapılarını bul (saf)."""
    out: list[Pattern2618] = []
    for i in range(len(pivots) - 3):
        a, b, c, d = pivots[i:i + 4]
        if a.price <= 0 or c.price <= 0:
            continue

        # Boğa: çift DİP — low, high, low, high
        if a.kind == "low" and b.kind == "high" and c.kind == "low" and d.kind == "high":
            if abs(a.price - c.price) / a.price > eq_tol:
                continue                              # eşit dip değil
            if d.price <= b.price:
                continue                              # neckline (3) kırılmadı
            leg = d.price - c.price
            if leg <= 0:
                continue
            out.append(Pattern2618(
                direction="bull", points=(a, b, c, d),
                entry=d.price - FIB_ENTRY * leg,
                stop=c.price,
                tp1=d.price,
                tp2=d.price + FIB_EXT * leg,
            ))

        # Ayı: çift TEPE — high, low, high, low
        elif a.kind == "high" and b.kind == "low" and c.kind == "high" and d.kind == "low":
            if abs(a.price - c.price) / a.price > eq_tol:
                continue
            if d.price >= b.price:
                continue
            leg = c.price - d.price
            if leg <= 0:
                continue
            out.append(Pattern2618(
                direction="bear", points=(a, b, c, d),
                entry=d.price + FIB_ENTRY * leg,
                stop=c.price,
                tp1=d.price,
                tp2=d.price - FIB_EXT * leg,
            ))

    return out


def detect_two_618(klines, threshold: float) -> list[Pattern2618]:
    """klines'ten fraktalları çıkarıp 2-618 yapılarını bul (kolaylık sarmalayıcı)."""
    return find_two_618(find_pivots(klines, threshold))
