"""include_abcd=False → standalone AB=CD ailesi taranmaz (sadece harmonikler)."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from tests.synthetic import make_pivots, make_xabcd_klines


def _klines():
    # (0.5, 0.5, 1.0) komb: en az bir standalone AB=CD üretir (probe ile bulundu)
    prices, kinds = make_pivots(0.5, 0.5, 1.0)
    return make_xabcd_klines(prices, kinds, bars_per_leg=10, base_time=1_700_000_000_000)


def _scan(include_abcd):
    return scan_klines(_klines(), "BTCUSDT", "60m", zigzag_threshold=0.01,
                       min_rr=0.0, include_abcd=include_abcd)


def test_abcd_present_by_default():
    fams = {s.pattern_family for s in _scan(True)}
    assert "abcd" in fams, "varsayılan tarama AB=CD üretmeli (test verisi geçersiz)"


def test_no_abcd_excludes_only_abcd_family():
    full = _scan(True)
    harmonic_only = _scan(False)
    # AB=CD ailesi tamamen gitti
    assert all(s.pattern_family != "abcd" for s in harmonic_only)
    # Gerçek harmonikler (xabcd/shark/cypher) AYNEN korundu
    full_non_abcd = sorted((s.pattern_name, s.pivots["D"].time)
                           for s in full if s.pattern_family != "abcd")
    kept = sorted((s.pattern_name, s.pivots["D"].time) for s in harmonic_only)
    assert kept == full_non_abcd
    # Toplam azaldı (en az bir AB=CD elendi)
    assert len(harmonic_only) < len(full)
