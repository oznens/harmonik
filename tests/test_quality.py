"""Q (Quality) skoru ve HTF/LTF testleri."""
from __future__ import annotations

from terminal.detection.scanner import scan_klines
from terminal.quality.htf_ltf import alignment, detect_trend, htf_for
from terminal.quality.score import categorize, compute_q
from tests.synthetic import (
    butterfly_bull,
    crab_bull,
    gartley_bull,
    make_xabcd_klines,
    to_bear,
)


# ---- HTF/LTF eşleme ----

def test_htf_mapping_known_intervals():
    assert htf_for("15m") == "60m"
    assert htf_for("60m") == "4h"
    assert htf_for("4h") == "1d"
    assert htf_for("1d") == "1W"
    assert htf_for("1W") is None  # daha üst yok


def test_detect_trend_uptrend():
    # Düz artan close'lar → bull
    klines = [{"close": 100 + i * 0.5} for i in range(120)]
    assert detect_trend(klines) == "bull"


def test_detect_trend_downtrend():
    klines = [{"close": 200 - i * 0.5} for i in range(120)]
    assert detect_trend(klines) == "bear"


def test_detect_trend_neutral_short_data():
    klines = [{"close": 100} for _ in range(20)]
    assert detect_trend(klines) == "neutral"


def test_alignment_logic():
    assert alignment("bull", "bull") is True
    assert alignment("bear", "bear") is True
    assert alignment("bull", "bear") is False
    assert alignment("bear", "bull") is False
    assert alignment("bull", "neutral") is None
    assert alignment("bear", None) is None


# ---- Q score ----

def _ideal_gartley_setup(htf_trend=None):
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    # HTF için: bull trend simülasyonu (artan close'lar)
    htf = None
    if htf_trend is not None:
        if htf_trend == "bull":
            htf = [{"close": 100 + i * 0.5} for i in range(120)]
        elif htf_trend == "bear":
            htf = [{"close": 200 - i * 0.5} for i in range(120)]
        elif htf_trend == "neutral":
            htf = [{"close": 100} for _ in range(120)]
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf)
    return next(s for s in setups if s.pattern_name == "Gartley")


def test_compute_q_ideal_gartley_no_htf():
    s = _ideal_gartley_setup(htf_trend=None)
    qr = compute_q(s, htf_trend=None)
    # HTF yok → HTF bileşeni 0. Ideal Gartley AB=CD onaylı: 55-80 bandında.
    assert 55 <= qr.score <= 85
    assert qr.components["htf"] == 0
    # AB=CD onayı çıkmalı
    assert qr.components["ab_cd"] == 15


def test_compute_q_ideal_gartley_bull_with_bull_htf():
    s = _ideal_gartley_setup(htf_trend="bull")
    qr = compute_q(s, htf_trend="bull")
    # +15 HTF puanı: ideal Gartley + bull HTF → 70+ (Kaliteli)
    assert qr.score >= 70
    assert qr.components["htf"] == 15
    assert qr.category == "Kaliteli"


def test_compute_q_ideal_gartley_bull_with_bear_htf():
    s = _ideal_gartley_setup(htf_trend=None)  # bull
    qr = compute_q(s, htf_trend="bear")
    # HTF zıt → HTF puanı 0
    assert qr.components["htf"] == 0


def test_categorize_thresholds():
    assert categorize(45) == "Riskli"
    assert categorize(50) == "Normal"
    assert categorize(69) == "Normal"
    assert categorize(70) == "Kaliteli"
    assert categorize(95) == "Kaliteli"


# ---- scan_klines entegrasyonu ----

def test_scan_with_htf_marks_aligned():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    htf = [{"close": 100 + i * 0.5} for i in range(120)]  # bull
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.direction == "bull"
    assert s.htf_trend == "bull"
    assert s.htf_aligned is True
    assert s.elenen is False
    assert s.q_score > 0
    assert s.q_category in ("Normal", "Kaliteli")


def test_scan_with_opposing_htf_marks_elenen():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    htf = [{"close": 200 - i * 0.5} for i in range(120)]  # bear
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.direction == "bull"
    assert s.htf_trend == "bear"
    assert s.htf_aligned is False
    assert s.elenen is True


def test_scan_without_htf_leaves_alignment_none():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=None)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.htf_trend is None
    assert s.htf_aligned is None
    assert s.elenen is False  # default
