"""Market yapısı (swing) + CHoCH/MSB onayı (#3 yapısal filtre — Price Action)."""
from __future__ import annotations

from terminal.detection.structure import check_choch, swing_points


def _bar(h, l, c, t):
    return {"open_time": t, "close_time": t + 1, "open": c, "high": h,
            "low": l, "close": c, "volume": 100, "quote_volume": 1000}


# Bull bağlam: düşüşte lower high (idx2=105), sonra idx6 kapanışı 106 > 105 → CHoCH.
_BULL = [
    _bar(100, 98, 99, 10),
    _bar(101, 99, 100, 20),
    _bar(105, 103, 104, 30),   # swing high
    _bar(102, 100, 101, 40),
    _bar(99, 97, 98, 50),      # swing low
    _bar(104, 98, 103, 60),
    _bar(107, 103, 106, 70),   # close 106 > 105 → CHoCH onayı
]


def test_swing_points_finds_high_and_low():
    sw = swing_points(_BULL, left=2, right=2)
    highs = [s for s in sw if s.kind == "high"]
    lows = [s for s in sw if s.kind == "low"]
    assert any(s.index == 2 and s.price == 105 for s in highs)
    assert any(s.index == 4 and s.price == 97 for s in lows)


def test_choch_bull_confirms_on_break():
    r = check_choch(_BULL, "bull", left=2, right=2)
    assert r.confirmed
    assert r.broken_level == 105
    assert r.confirm_idx == 6
    assert r.confirm_time == 70
    assert r.confirm_close == 106


def test_choch_bull_no_confirm_when_no_break():
    # Son barı son swing high'ın (105) ALTINDA kapat → onay yok.
    bars = _BULL[:-1] + [_bar(104, 100, 103, 70)]
    r = check_choch(bars, "bull", left=2, right=2)
    assert not r.confirmed
    assert r.confirm_idx is None


def test_choch_max_bars_timeout():
    # Kırılım idx6'da; max_bars=6 → idx0..5 taranır, onaya ulaşılmaz.
    r = check_choch(_BULL, "bull", left=2, right=2, max_bars=6)
    assert not r.confirmed


def test_choch_bear_confirms_on_break():
    # Bear: yükselişte higher low (idx2=95 swing low), idx6 kapanışı 94 < 95 → CHoCH.
    bars = [
        _bar(102, 100, 101, 10),
        _bar(101, 99, 100, 20),
        _bar(97, 95, 96, 30),     # swing low
        _bar(100, 98, 99, 40),
        _bar(103, 101, 102, 50),  # swing high
        _bar(102, 96, 97, 60),
        _bar(97, 93, 94, 70),     # close 94 < 95 → bear CHoCH
    ]
    r = check_choch(bars, "bear", left=2, right=2)
    assert r.confirmed
    assert r.broken_level == 95
    assert r.confirm_idx == 6


def test_choch_empty_is_not_confirmed():
    assert not check_choch([], "bull").confirmed
