"""2-618 Stratejisi (Çift Dip/Tepe + 0.618 giriş) testleri."""
from __future__ import annotations

from terminal.detection.pivots import Pivot
from terminal.detection.two_618 import find_two_618

T0 = 1_700_000_000_000
MS = 3_600_000


def _piv(i, price, kind):
    return Pivot(index=i, time=T0 + i * MS, price=price, kind=kind)


def test_bull_double_bottom():
    # 2=100(dip) 3=120(neckline) 4=101(≈dip) 5=140(neckline'ı aşar)
    pivs = [_piv(0, 100, "low"), _piv(2, 120, "high"),
            _piv(4, 101, "low"), _piv(6, 140, "high")]
    pats = find_two_618(pivs)
    assert len(pats) == 1
    p = pats[0]
    assert p.direction == "bull"
    leg = 140 - 101                                  # 39
    assert abs(p.entry - (140 - 0.618 * leg)) < 1e-6   # ~115.9
    assert p.stop == 101 and p.tp1 == 140
    assert abs(p.tp2 - (140 + 0.272 * leg)) < 1e-6     # ~150.6
    assert abs(p.rr - 1.618) < 0.01                    # 0.618/0.382


def test_bear_double_top():
    pivs = [_piv(0, 100, "high"), _piv(2, 80, "low"),
            _piv(4, 102, "high"), _piv(6, 55, "low")]
    pats = find_two_618(pivs)
    assert len(pats) == 1 and pats[0].direction == "bear"
    p = pats[0]
    leg = 102 - 55                                   # 47
    assert abs(p.entry - (55 + 0.618 * leg)) < 1e-6
    assert p.stop == 102 and p.tp1 == 55
    assert abs(p.tp2 - (55 - 0.272 * leg)) < 1e-6


def test_reject_unequal_double_bottom():
    # 2=100, 4=110 → %10 fark, eşit dip değil (tol %3)
    pivs = [_piv(0, 100, "low"), _piv(2, 120, "high"),
            _piv(4, 110, "low"), _piv(6, 140, "high")]
    assert find_two_618(pivs) == []


def test_reject_neckline_not_broken():
    # 5=115 < 3=120 → neckline kırılmadı, onay yok
    pivs = [_piv(0, 100, "low"), _piv(2, 120, "high"),
            _piv(4, 101, "low"), _piv(6, 115, "high")]
    assert find_two_618(pivs) == []


def test_eq_tol_configurable():
    pivs = [_piv(0, 100, "low"), _piv(2, 120, "high"),
            _piv(4, 105, "low"), _piv(6, 140, "high")]
    assert find_two_618(pivs, eq_tol=0.02) == []        # %5 fark > %2
    assert len(find_two_618(pivs, eq_tol=0.06)) == 1     # %5 fark < %6
