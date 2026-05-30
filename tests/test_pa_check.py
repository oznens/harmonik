"""PA giriş denetimi: 3 kontrol noktası (yer/zaman/stop) + pa_stop seviyesi."""
from __future__ import annotations

import types

from terminal.quality.pa_check import format_checklist, pa_checklist, pa_stop
from terminal.quality.smc import compute_smc


def _bar(o, h, l, c, t):
    return {"open_time": t, "close_time": t + 1, "open": o, "high": h,
            "low": l, "close": c, "volume": 100, "quote_volume": 1000}


def _setup(direction, d_time, d_price, stop, entry=None, pattern="Bat"):
    piv = {"D": types.SimpleNamespace(time=d_time, price=d_price)}
    return types.SimpleNamespace(
        pivots=piv, direction=direction, pattern_name=pattern,
        symbol="T", interval="60m", entry=entry if entry is not None else d_price,
        stop=stop)


# D fiyatı (102), D'den önce oluşmuş bull FVG'nin (100..105) içinde.
_KL = [
    _bar(99, 99, 98, 98, 10),
    _bar(100, 100, 99, 99, 20),     # high=100
    _bar(103, 108, 103, 107, 30),   # displacement
    _bar(106, 107, 105, 106, 40),   # low=105 → bull FVG 100..105
    _bar(104, 104, 103, 103, 50),
    _bar(103, 103, 102, 102, 60),
    _bar(102, 103, 101, 102, 70),   # D barı
]


def test_pa_stop_uses_fvg_bottom():
    s = _setup("bull", d_time=70, d_price=102, stop=99.0)
    sr = compute_smc(s, _KL)
    assert sr.fvg and sr.fvg_zone["bottom"] == 100
    level, basis = pa_stop(s, _KL, sr)
    assert basis == "fvg"
    assert level < 100 and abs(level - 100 * (1 - 0.0005)) < 1e-6


def test_checklist_zone_yes_stop_no_when_harmonic():
    # Stop 99 → FVG tabanı 100'ün altında ama PA stop ~99.95'ten uzak (sapma>0.3%)
    s = _setup("bull", d_time=70, d_price=102, stop=99.0, entry=102.0)
    c = pa_checklist(s, _KL)  # ltf yok → choch None
    assert c.zone_ok is True          # #1 FVG
    assert c.choch_ok is None         # #2 LTF verisi yok
    assert c.stop_ok is False         # #3 harmonik stop, PA seviyesine uzak
    assert c.pa_stop_level is not None
    assert not c.all_pass()


def test_checklist_stop_ok_when_at_pa_level():
    # Stop tam PA seviyesinde (~99.95) → #3 EVET
    s = _setup("bull", d_time=70, d_price=102, stop=99.95, entry=102.0)
    c = pa_checklist(s, _KL)
    assert c.stop_ok is True


def test_checklist_choch_confirmed_with_ltf():
    s = _setup("bull", d_time=70, d_price=102, stop=99.95, entry=102.0)
    # LTF: D (t=70) sonrası bull CHoCH veren dizi
    ltf = [
        _bar(101, 102, 100, 101, 80),
        _bar(100, 101, 99, 100, 85),
        _bar(104, 105, 103, 104, 90),   # swing high 105
        _bar(101, 102, 100, 101, 95),
        _bar(98, 99, 97, 98, 100),
        _bar(103, 104, 98, 103, 105),
        _bar(106, 107, 103, 106, 110),  # close 106 > 105 → CHoCH
    ]
    c = pa_checklist(s, _KL, ltf_klines=ltf)
    assert c.choch_ok is True
    assert c.all_pass() is True
    txt = format_checklist(s, c)
    assert "EVET" in txt and "PA CHECK" in txt


def test_checklist_no_zone():
    s = _setup("bull", d_time=50, d_price=100, stop=99.0)
    flat = [_bar(100, 101, 99, 100, t * 10) for t in range(6)]
    c = pa_checklist(s, flat)
    assert c.zone_ok is False
    assert c.pa_stop_level is None
    assert c.stop_ok is False


def test_pa_stop_sweep_bull():
    # Sweep: D barı eski dibin altına iğne atıp üstünde kapatır → stop iğne altı
    kl = [
        _bar(105, 106, 100, 104, 10),   # old_low 100
        _bar(104, 105, 101, 103, 20),
        _bar(103, 104, 98, 102, 30),    # D: low 98 < 100, close 102 > 100 → sweep
    ]
    s = _setup("bull", d_time=30, d_price=102, stop=95.0)
    sr = compute_smc(s, kl)
    assert sr.sweep
    level, basis = pa_stop(s, kl, sr)
    assert basis == "sweep iğnesi"
    assert abs(level - 98 * (1 - 0.0005)) < 1e-6
