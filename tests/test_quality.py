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
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf, min_rr=0.0)
    return next(s for s in setups if s.pattern_name == "Gartley")


def test_compute_q_ideal_gartley_no_htf():
    s = _ideal_gartley_setup(htf_trend=None)
    qr = compute_q(s, htf_trend=None)
    # Ideal Gartley AB=CD onaylı, HTF artık skora dahil değil.
    assert 60 <= qr.score <= 100
    assert "htf" not in qr.components  # HTF bileşeni kaldırıldı
    assert qr.components["ab_cd"] == 15


def test_compute_q_htf_does_not_affect_score():
    """HTF trend artık Q skorunu etkilemiyor (bilgi olarak setup.htf_aligned'de)."""
    s = _ideal_gartley_setup(htf_trend=None)
    q_no_htf = compute_q(s, htf_trend=None).score
    q_bull_htf = compute_q(s, htf_trend="bull").score
    q_bear_htf = compute_q(s, htf_trend="bear").score
    assert q_no_htf == q_bull_htf == q_bear_htf


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
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.direction == "bull"
    assert s.htf_trend == "bull"
    assert s.htf_aligned is True
    assert s.elenen is False
    assert s.q_score > 0
    assert s.q_category in ("Normal", "Kaliteli")


def test_scan_with_opposing_htf_records_misalignment():
    """HTF zıt → htf_aligned=False, ama Gartley elenen DEĞİL (harmonik mean
    reversion HTF zıt'ta daha iyi). Sadece HTF_OPPOSITE_PENALIZED listesindeki
    pattern'ler (örn. 1.62 AB=CD) HTF zıt'ta elenen sayılır."""
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    htf = [{"close": 200 - i * 0.5} for i in range(120)]  # bear
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=htf, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.direction == "bull"
    assert s.htf_trend == "bear"
    assert s.htf_aligned is False
    assert s.elenen is False  # Gartley HTF_OPPOSITE_PENALIZED'de değil


def test_penalized_pattern_marked_elenen_on_htf_opposite():
    """HTF_OPPOSITE_PENALIZED listesindeki pattern HTF zıt'ta elenen olur."""
    from terminal.detection.models import Setup
    from terminal.detection.pivots import Pivot
    from terminal.detection.scanner import _is_elenen
    p = Pivot(index=0, time=0, price=100.0, kind="high")
    s = Setup(
        symbol="X", interval="15m", pattern_name="1.62 AB=CD", direction="bull",
        pivots={"X": p, "A": p, "B": p, "C": p, "D": p},
        b_ratio=0, c_ratio=0, d_ratio=0, bc_proj=0, cd_ab_ratio=0,
        ab_cd_equivalent=False, prz_low=0, prz_high=0, prz_components=[],
        entry=0, stop=0, tp1=0, tp2=0, detected_at=0, pattern_family="abcd",
    )
    s.htf_aligned = False
    assert _is_elenen(s) is True
    s.htf_aligned = True
    assert _is_elenen(s) is False
    s.htf_aligned = None
    assert _is_elenen(s) is False


def test_scan_without_htf_leaves_alignment_none():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, htf_klines=None, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    assert s.htf_trend is None
    assert s.htf_aligned is None
    assert s.elenen is False  # default
