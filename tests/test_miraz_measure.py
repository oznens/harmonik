"""Miraz ölçüm çekirdeği testleri (saf) — Bucket / harmonic_buckets / 2-618 sim."""
from __future__ import annotations

from terminal.detection.pivots import Pivot
from terminal.detection.two_618 import Pattern2618
from terminal.quality.miraz_measure import (
    Bucket, HarmonicRecord, format_buckets, harmonic_buckets, simulate_two_618,
)


def _pat(direction="bull", entry=100.0, stop=90.0, tp1=120.0):
    p = Pivot(0, 0, 100, "low")
    return Pattern2618(direction=direction, points=(p, p, p, p),
                       entry=entry, stop=stop, tp1=tp1, tp2=tp1 + 10)


def _bar(h, l):
    return {"open_time": 0, "close_time": 0, "open": (h + l) / 2,
            "high": h, "low": l, "close": (h + l) / 2}


def test_bucket_math():
    b = Bucket("x")
    b.add("TP", 1.5)
    b.add("STOP", -1.0)
    b.add("EO", 0.0)
    assert b.passed == 3 and b.tp == 1 and b.stop == 1 and b.other == 1
    assert b.decided == 2 and b.win_rate == 50.0
    assert b.total_r == 0.5


def test_harmonic_buckets_filtering():
    recs = [
        HarmonicRecord("TP", 1.0, fraktal=True, pamonic=True),
        HarmonicRecord("STOP", -1.0, fraktal=True, pamonic=False),
        HarmonicRecord("TP", 1.0, fraktal=False, pamonic=True),
        HarmonicRecord("STOP", -1.0, fraktal=False, pamonic=False),
    ]
    baz, frak, pamo, both = harmonic_buckets(recs)
    assert baz.passed == 4 and baz.win_rate == 50.0 and baz.total_r == 0.0
    assert frak.passed == 2 and frak.win_rate == 50.0
    assert pamo.passed == 2 and pamo.tp == 2 and pamo.win_rate == 100.0 and pamo.total_r == 2.0
    assert both.passed == 1 and both.tp == 1 and both.win_rate == 100.0


def test_simulate_two_618_tp():
    # entry=100 fill (low<=100), sonra tp1=120 vurulur
    fut = [_bar(101, 99), _bar(121, 110)]
    assert simulate_two_618(_pat("bull"), fut) == "TP"


def test_simulate_two_618_stop():
    fut = [_bar(101, 99), _bar(95, 89)]      # fill sonra stop=90 (low<=90)
    assert simulate_two_618(_pat("bull"), fut) == "STOP"


def test_simulate_two_618_eo_missed():
    # 0.618'e (entry=100) inmeden tp1=120'yi geçer → kaçtı (EO)
    fut = [_bar(121, 101)]
    assert simulate_two_618(_pat("bull"), fut) == "EO"


def test_simulate_two_618_bear_tp():
    # bear: entry=100 (high>=100 fill), tp1=80 (low<=80)
    fut = [_bar(101, 99), _bar(90, 79)]
    assert simulate_two_618(_pat("bear", entry=100, stop=110, tp1=80), fut) == "TP"


def test_format_buckets_text():
    txt = format_buckets("Başlık", [Bucket("Baz", passed=10, tp=4, stop=2, total_r=2.0)])
    assert "Başlık" in txt and "Baz" in txt and "66.7%" in txt   # 4/(4+2)
