"""Scanner uçtan uca testleri (sentetik kline → Setup)."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from tests.synthetic import (
    bat_bull,
    butterfly_bull,
    crab_bull,
    gartley_bull,
    make_xabcd_klines,
    to_bear,
)


def test_scan_finds_synthetic_gartley_bull():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    assert len(setups) >= 1
    gartley = [s for s in setups if s.pattern_name == "Gartley"]
    assert len(gartley) == 1
    s = gartley[0]
    assert s.direction == "bull"
    # Entry, D ideal civarı olmalı (0.786 XA)
    assert abs(s.entry - prices[4]) / prices[4] < 0.01
    # Stop X seviyesinin altında (bull → A - 1.0*XA = X)
    assert s.stop <= prices[0] + 0.001
    # TP1 (0.382 IPO) entry'nin üstünde olmalı (bull)
    assert s.tp1 > s.entry


def test_scan_finds_synthetic_bat_bull():
    prices, kinds = bat_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    bat = [s for s in setups if s.pattern_name == "Bat"]
    assert len(bat) == 1
    s = bat[0]
    assert s.direction == "bull"
    # Bat stop > 1.13 XA — yani A - 1.13 * XA = X - 0.13 * XA
    xa = prices[1] - prices[0]
    expected_stop = prices[1] - 1.13 * xa
    assert abs(s.stop - expected_stop) < 0.5


def test_scan_finds_synthetic_butterfly_bull():
    prices, kinds = butterfly_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    butterflies = [s for s in setups if s.pattern_name == "Butterfly"]
    assert len(butterflies) == 1


def test_scan_finds_synthetic_crab_bull():
    prices, kinds = crab_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    crabs = [s for s in setups if s.pattern_name == "Crab"]
    assert len(crabs) == 1


def test_scan_finds_bear_variant():
    prices, kinds = to_bear(*gartley_bull())
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    bears = [s for s in setups if s.direction == "bear"]
    assert len(bears) >= 1


def test_scan_empty_klines_returns_empty():
    assert scan_klines([], "TEST", "60m") == []


def test_scan_handles_insufficient_pivots():
    # Sadece 3 pivot oluşacak şekilde — 5 pivot bulunamayacak
    klines = []
    for i in range(20):
        klines.append({
            "open_time": i * 1000, "close_time": i * 1000 + 999,
            "open": 100, "high": 100.5, "low": 99.5, "close": 100,
            "volume": 100, "quote_volume": 1000,
        })
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.05)
    assert setups == []


def test_prz_contains_d_ideal_price():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    # 0.786 XA = entry, PRZ aralığında olmalı
    assert s.prz_low <= s.entry <= s.prz_high
