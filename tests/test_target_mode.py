"""Hedef (TP) modeli testleri — terminalMiraz referans 'rr1' (sabit 1:1 R:R)."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from tests.synthetic import gartley_bull, make_xabcd_klines, to_bear


def _scan(prices, kinds, mode):
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=1_700_000_000_000)
    return scan_klines(kl, "BTCUSDT", "60m", zigzag_threshold=0.01,
                       min_rr=0.0, target_mode=mode)


def test_rr1_target_is_exactly_one_r_bull():
    prices, kinds = gartley_bull()
    setups = _scan(prices, kinds, "rr1")
    assert setups, "en az bir setup bulunmalı"
    for s in setups:
        risk = abs(s.stop - s.entry)
        # Bull: hedef entry'nin ÜSTÜNDE, mesafe = risk (1R)
        assert s.tp1 > s.entry
        assert abs((s.tp1 - s.entry) - risk) < 1e-6
        # TP2 = 2R (genişletilmiş)
        assert abs((s.tp2 - s.entry) - 2 * risk) < 1e-6


def test_rr1_target_is_exactly_one_r_bear():
    prices, kinds = to_bear(*gartley_bull())
    setups = _scan(prices, kinds, "rr1")
    assert setups
    for s in setups:
        risk = abs(s.stop - s.entry)
        # Bear: hedef entry'nin ALTINDA, mesafe = risk (1R)
        assert s.tp1 < s.entry
        assert abs((s.entry - s.tp1) - risk) < 1e-6
        assert abs((s.entry - s.tp2) - 2 * risk) < 1e-6


def test_structural_differs_from_rr1():
    prices, kinds = gartley_bull()
    structural = _scan(prices, kinds, "structural")
    rr1 = _scan(prices, kinds, "rr1")
    # Aynı pivotlar → aynı sayıda setup, ama TP1 yapısal (B) ≠ 1R hedef
    assert len(structural) == len(rr1)
    s0, r0 = structural[0], rr1[0]
    assert s0.entry == r0.entry and s0.stop == r0.stop   # entry/stop aynı
    assert s0.tp1 != r0.tp1                               # hedef farklı


def test_default_is_structural():
    """target_mode verilmezse davranış DEĞİŞMEZ (yapısal B/A hedefleri)."""
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=1_700_000_000_000)
    default = scan_klines(kl, "BTCUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    structural = _scan(prices, kinds, "structural")
    assert [s.tp1 for s in default] == [s.tp1 for s in structural]
