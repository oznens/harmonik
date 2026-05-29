"""ONAYLI giriş (entry_mode='confirm'): D sonrası BOS bekler, fakeout'u eler."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from terminal.karakter.simulator import simulate_outcome
from tests.synthetic import gartley_bull, make_xabcd_klines


def _setup():
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "T", "60m", zigzag_threshold=0.01, min_rr=0.0)[0]
    assert s.direction == "bull"  # stop < entry < tp1
    return s


def _bar(o, h, l, c, t):
    return {"open_time": t, "close_time": t + 1, "open": o, "high": h,
            "low": l, "close": c, "volume": 100, "quote_volume": 1000}


def test_confirm_enters_on_bos_then_tp():
    s = _setup()
    e, tp = s.entry, s.tp1
    future = [
        _bar(e, e + 0.2, e - 0.2, e + 0.1, 1),          # bar0
        _bar(e + 0.1, e + 0.5, e, e + 0.4, 2),          # bar1: close > bar0.high → BOS
        _bar(e + 0.4, tp + 0.5, e + 0.3, tp, 3),        # bar2: giriş barı; high>=tp1 → TP
    ]
    o = simulate_outcome(s, future, entry_mode="confirm")
    assert o.outcome == "TP"
    assert o.entered_price == future[2]["open"]          # BOS sonrası bar açılışı


def test_confirm_eo_when_stop_before_bos():
    s = _setup()
    e, st = s.entry, s.stop
    future = [
        _bar(e, e + 0.1, e - 0.1, e - 0.05, 1),          # bar0
        _bar(e - 0.05, e, st - 0.1, st - 0.1, 2),        # bar1: low<=stop → onay öncesi EO
    ]
    o = simulate_outcome(s, future, entry_mode="confirm")
    assert o.outcome == "EO"
    assert o.entered_price is None                        # işlem AÇILMADI


def test_confirm_eo_when_no_bos():
    s = _setup()
    e = s.entry
    # Hiç BOS yok (kapanış hep önceki high altında), stop'a da değmez → EO
    future = [_bar(e, e + 0.1, e - 0.05, e - 0.02, t) for t in range(1, 6)]
    o = simulate_outcome(s, future, entry_mode="confirm")
    assert o.outcome == "EO"
    assert o.entered_price is None
