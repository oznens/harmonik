"""2h resample (60m → 2h birleştirme) testleri — MEXC native Hour2 yok."""
from __future__ import annotations

from terminal.data.mexc_futures import _resample, _INTERVAL_SECONDS, _RESAMPLE_FROM

H = 3_600_000   # 1 saat ms
T0 = 1_700_000_000_000
# T0'ı 2h sınırına hizala (çift saat)
T0 = (T0 // (2 * H)) * (2 * H)


def _k(i, o, h, l, c, v=10.0):
    ot = T0 + i * H
    return {"open_time": ot, "close_time": ot + H - 1,
            "open": o, "high": h, "low": l, "close": c,
            "volume": v, "quote_volume": v * 100}


def test_resample_basic_ohlcv():
    # 2 ardışık 60m → 1 adet 2h mum
    base = [_k(0, 100, 105, 99, 103), _k(1, 103, 108, 102, 106)]
    out = _resample(base, 2, _INTERVAL_SECONDS["2h"])
    assert len(out) == 1
    b = out[0]
    assert b["open"] == 100              # ilk açılış
    assert b["close"] == 106            # son kapanış
    assert b["high"] == 108             # max high
    assert b["low"] == 99               # min low
    assert b["volume"] == 20.0          # toplam hacim
    assert b["open_time"] == T0
    assert b["close_time"] == T0 + 2 * H - 1


def test_resample_alignment_even_hours():
    # 4 mum → 2 adet 2h mum, çift saat sınırına hizalı
    base = [_k(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(4)]
    out = _resample(base, 2, _INTERVAL_SECONDS["2h"])
    assert len(out) == 2
    assert out[0]["open_time"] == T0
    assert out[1]["open_time"] == T0 + 2 * H


def test_resample_partial_last_group():
    # 3 mum → 2 grup; ikincisi yarım (1 mum) ama yine döner (forming bar)
    base = [_k(i, 100, 100, 100, 100) for i in range(3)]
    out = _resample(base, 2, _INTERVAL_SECONDS["2h"])
    assert len(out) == 2
    # yarım grubun close_time'ı yine tam 2h penceresi sonu (gelecekte → forming)
    assert out[1]["close_time"] == out[1]["open_time"] + 2 * H - 1


def test_resample_passthrough_factor1():
    base = [_k(0, 1, 1, 1, 1)]
    assert _resample(base, 1, 3600) is base   # factor<=1 → değişmeden


def test_resample_empty():
    assert _resample([], 2, 7200) == []


def test_resample_config_registered():
    # 2h kayıtlı: 60m'den 2x resample, doğru saniye
    assert _RESAMPLE_FROM["2h"] == ("60m", 2)
    assert _INTERVAL_SECONDS["2h"] == 7200
    assert _INTERVAL_SECONDS["8h"] == 28800
