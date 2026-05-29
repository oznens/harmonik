"""Karakter lab simulator + score testleri."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.karakter.score import compute_stats
from terminal.karakter.simulator import simulate_outcome
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _gartley_setup():
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    return s, klines


# ---- simulate_outcome ----

def test_simulate_eo_no_entry_in_timeout():
    s, _ = _gartley_setup()
    # Hiçbiri entry'ye değmiyor (fiyat çok yüksek)
    future = [{"open_time": i * 3_600_000 + 1_700_000_000_000,
               "close_time": i * 3_600_000 + 1_700_000_003_599_999,
               "open": s.entry + 50, "high": s.entry + 51,
               "low": s.entry + 49, "close": s.entry + 50,
               "volume": 100, "quote_volume": 1000} for i in range(70)]
    o = simulate_outcome(s, future, aday_timeout=60, force_immediate_entry=False)
    assert o.outcome == "EO"
    assert o.entered_idx is None


def test_simulate_tp_after_entry():
    s, _ = _gartley_setup()
    # 1. bar entry tetikler, 2. bar TP1'i vurur
    base_t = 1_700_000_000_000
    future = [
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.entry, "low": s.entry - 0.01, "close": s.entry,
         "volume": 100, "quote_volume": 1000},
        {"open_time": base_t + 3_600_000, "close_time": base_t + 7_199_999,
         "open": s.entry, "high": s.tp1 + 0.1, "low": s.entry, "close": s.tp1,
         "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "TP"
    assert o.entered_idx == 0
    assert o.exited_idx == 1


def test_simulate_stop_after_entry():
    s, _ = _gartley_setup()
    base_t = 1_700_000_000_000
    future = [
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.entry, "low": s.entry - 0.01, "close": s.entry,
         "volume": 100, "quote_volume": 1000},
        {"open_time": base_t + 3_600_000, "close_time": base_t + 7_199_999,
         "open": s.entry, "high": s.entry, "low": s.stop - 0.1, "close": s.stop - 0.05,
         "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "STOP"


def test_simulate_entry_bar_sl_touched_skips_to_eo():
    """Giriş barında fiyat hem entry'ye hem SL'e değiyorsa reversal yok —
    pasif giriş stratejisi: kullanıcı bu setupta emir koymaz. EO işaretle."""
    s, _ = _gartley_setup()  # bull setup
    base_t = 1_700_000_000_000
    future = [
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.tp1 + 0.5, "low": s.stop - 0.5, "close": s.entry,
         "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "EO"


def test_simulate_entry_bar_only_entry_touched_active():
    """Giriş barında sadece entry touch, SL touch yok → Aktif (TP kontrolü sonraki barda)."""
    s, _ = _gartley_setup()  # bull setup
    base_t = 1_700_000_000_000
    future = [
        # low entry'ye değdi ama stop'a değmedi; high tp'ye değdi ama bu sayılmaz
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.tp1 + 0.5, "low": s.entry - 0.01,
         "close": s.entry, "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "Aktif"


def test_simulate_ambiguous_close_below_entry_is_stop():
    """Aynı bar TP+SL touch + close ENTRY'nin ALTINDA → STOP (zararda kapandı)."""
    s, _ = _gartley_setup()
    base_t = 1_700_000_000_000
    future = [
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.entry, "low": s.entry - 0.01, "close": s.entry,
         "volume": 100, "quote_volume": 1000},
        {"open_time": base_t + 3_600_000, "close_time": base_t + 7_199_999,
         "open": s.entry, "high": s.tp1 + 0.5, "low": s.stop - 0.5,
         "close": s.entry - 0.01,  # close entry'nin ALTINDA — STOP
         "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "STOP"
    assert o.ambiguous is True


def test_simulate_ambiguous_always_stop_matches_live():
    """Aynı bar TP+SL touch → close yukarıda OLSA BİLE STOP (canlı _check_aktif
    ile tutarlı: bar içi sıra bilinmez, tutucu STOP). Backtest WR'si canlı paper
    ile karşılaştırılabilir olsun diye."""
    s, _ = _gartley_setup()
    base_t = 1_700_000_000_000
    future = [
        {"open_time": base_t, "close_time": base_t + 3_599_999,
         "open": s.entry, "high": s.entry, "low": s.entry - 0.01, "close": s.entry,
         "volume": 100, "quote_volume": 1000},
        {"open_time": base_t + 3_600_000, "close_time": base_t + 7_199_999,
         "open": s.entry, "high": s.tp1 + 0.5, "low": s.stop - 0.5,
         "close": s.entry + (s.tp1 - s.entry) * 0.5,  # close TP yarısında ama yine STOP
         "volume": 100, "quote_volume": 1000},
    ]
    o = simulate_outcome(s, future, force_immediate_entry=False)
    assert o.outcome == "STOP"
    assert o.ambiguous is True


def test_simulate_aday_still_open_when_future_short():
    s, _ = _gartley_setup()
    base_t = 1_700_000_000_000
    future = [
        # Sadece 5 bar — timeout'a uzak, entry yok
        {"open_time": base_t + i * 3_600_000, "close_time": base_t + i * 3_600_000 + 3_599_999,
         "open": s.entry + 50, "high": s.entry + 51, "low": s.entry + 49, "close": s.entry + 50,
         "volume": 100, "quote_volume": 1000} for i in range(5)
    ]
    o = simulate_outcome(s, future, aday_timeout=60, force_immediate_entry=False)
    assert o.outcome == "Aday"


# ---- score aggregation ----

def test_compute_stats_basic():
    outcomes = ["TP"] * 18 + ["STOP"] * 7 + ["ZI"] * 15 + ["EO"] * 3
    st = compute_stats(outcomes)
    assert st.tp_count == 18 and st.stop_count == 7
    assert st.zi_count == 15 and st.eo_count == 3
    assert abs(st.win_rate - 18 / 25) < 1e-6
    # decided=25, weight = 25/30 = 0.833
    expected = (18 / 25) * (25 / 30) * 100
    assert abs(st.karakter_score - round(expected, 2)) < 0.5


def test_compute_stats_empty():
    st = compute_stats([])
    assert st.sample_count == 0
    assert st.win_rate == 0.0
    assert st.karakter_score == 0.0


def test_compute_stats_full_weight_above_threshold():
    # 30+ decided ile tam ağırlık
    outcomes = ["TP"] * 24 + ["STOP"] * 6
    st = compute_stats(outcomes)
    assert abs(st.karakter_score - 80.0) < 0.1


# ---- store integration ----

def test_store_karakter_score_lookup(store: Store):
    # Bir lab koşusu simüle et — sample'lar ekle, agregasyon yap
    run_id = store.create_karakter_run(
        started_at=1_700_000_000_000, bars_per_pair=1000,
        symbols=["TEST"], intervals=["60m"],
    )
    # 5 TP + 1 STOP gartley sample
    from terminal.karakter.simulator import SimOutcome
    s, _ = _gartley_setup()
    for _ in range(5):
        store.add_karakter_sample(run_id, s, SimOutcome("TP", 0, 1, 1, 2))
    store.add_karakter_sample(run_id, s, SimOutcome("STOP", 0, 1, 1, 2))
    store.finish_karakter_run(run_id, 6)
    store.recompute_karakter_scores()

    # 'all' direction → 6 sample, WR=5/6
    res = store.get_karakter_score("TEST", "60m", "Gartley", direction="all")
    assert res is not None
    score, n = res
    assert n == 6
    # WR=0.833, weight=6/30=0.2 → score ≈ 16.67
    assert 15 < score < 18


def test_recompute_clears_old_scores(store: Store):
    run_id = store.create_karakter_run(1_700_000_000_000, 100, ["TEST"], ["60m"])
    from terminal.karakter.simulator import SimOutcome
    s, _ = _gartley_setup()
    store.add_karakter_sample(run_id, s, SimOutcome("TP", 0, 1, 1, 2))
    store.recompute_karakter_scores()
    assert store.get_karakter_score("TEST", "60m", "Gartley", "all") is not None

    # Sample'ları temizleyip tekrar hesaplayınca skor olmamalı
    store._conn.execute("DELETE FROM karakter_samples")
    store.recompute_karakter_scores()
    assert store.get_karakter_score("TEST", "60m", "Gartley", "all") is None
