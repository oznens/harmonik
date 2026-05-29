"""CHoCH giriş modu (entry_mode='choch'): LTF yapı kırılımı ile onaylı giriş."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from terminal.karakter.simulator import simulate_outcome
from tests.synthetic import gartley_bull, make_xabcd_klines


def _setup():
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "T", "60m", zigzag_threshold=0.01, min_rr=0.0)[0]
    assert s.direction == "bull"
    return s


def _bar(o, h, l, c, t):
    return {"open_time": t, "close_time": t + 1, "open": o, "high": h,
            "low": l, "close": c, "volume": 100, "quote_volume": 1000}


def _ltf_confirm():
    """LTF: idx6'da (open_time 35) bull CHoCH onayı veren dizi → tc=35."""
    return [
        _bar(99, 100, 98, 99, 5),
        _bar(100, 101, 99, 100, 10),
        _bar(104, 105, 103, 104, 15),   # swing high 105
        _bar(101, 102, 100, 101, 20),
        _bar(98, 99, 97, 98, 25),       # swing low
        _bar(103, 104, 98, 103, 30),
        _bar(106, 107, 103, 106, 35),   # close 106 > 105 → CHoCH onayı (tc=35)
    ]


def _ltf_no_confirm():
    bars = _ltf_confirm()[:-1]
    bars.append(_bar(103, 104, 100, 103, 35))  # son swing high (105) altında kapanış
    return bars


def test_choch_confirm_then_tp():
    s = _setup()
    e, tp, st = s.entry, s.tp1, s.stop
    # HTF future: bar t=0 (onay öncesi, stop yok), bar t=50 (tc=35 sonrası → giriş + TP)
    future = [
        _bar(e, e + 0.1, e - 0.1, e, 0),
        _bar(e, tp + 0.5, e - 0.1, tp, 50),
    ]
    assert future[0]["low"] > st  # onay öncesi stop yenmez
    o = simulate_outcome(s, future, entry_mode="choch", ltf_klines=_ltf_confirm())
    assert o.outcome == "TP"
    assert o.entered_price == future[1]["open"]   # onaydan sonraki bar açılışı
    assert o.entered_time == 50


def test_choch_eo_when_no_ltf():
    s = _setup()
    e = s.entry
    future = [_bar(e, e + 1, e - 0.1, e + 0.5, 50)]
    o = simulate_outcome(s, future, entry_mode="choch", ltf_klines=None)
    assert o.outcome == "EO"
    assert o.entered_price is None


def test_choch_eo_when_no_confirm():
    s = _setup()
    e = s.entry
    future = [_bar(e, e + 1, e - 0.1, e + 0.5, 50)]
    o = simulate_outcome(s, future, entry_mode="choch", ltf_klines=_ltf_no_confirm())
    assert o.outcome == "EO"
    assert o.entered_price is None


def test_choch_eo_when_stop_before_confirm():
    s = _setup()
    e, st = s.entry, s.stop
    # Onay (tc=35) öncesi HTF barında stop yenir → işlem AÇILMAZ.
    future = [
        _bar(e, e + 0.1, st - 0.1, st, 0),   # t=0 <= tc, low<=stop → EO
        _bar(e, e + 5, e, e + 4, 50),
    ]
    o = simulate_outcome(s, future, entry_mode="choch", ltf_klines=_ltf_confirm())
    assert o.outcome == "EO"
    assert o.entered_price is None


def test_choch_confirm_then_stop():
    s = _setup()
    e, st = s.entry, s.stop
    future = [
        _bar(e, e + 0.1, e - 0.1, e, 0),        # onay öncesi, stop yok
        _bar(e, e + 0.2, st - 0.1, st, 50),     # giriş barı; low<=stop → STOP
    ]
    o = simulate_outcome(s, future, entry_mode="choch", ltf_klines=_ltf_confirm())
    assert o.outcome == "STOP"
    assert o.entered_price == future[1]["open"]
