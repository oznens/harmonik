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


def test_run_lab_aligned_with_live_config(store: Store, monkeypatch):
    """run_lab varsayılanları CANLI sistemle aynı olmalı: scan rr1 + AB=CD'siz,
    karakter örneklemi limit (PRZ) girişten. (Karakter Skoru canlıyı yansıtsın.)"""
    import terminal.karakter.runner as runner
    from terminal.data.mexc_client import MexcError
    from terminal.detection.models import Pivot, Setup
    from terminal.karakter.simulator import SimOutcome

    step, base = 3_600_000, 1_700_000_000_000
    bars = [{"open_time": base + i * step, "close_time": base + i * step + step - 1,
             "open": 100.0 + i, "high": 100.5 + i, "low": 99.5 + i, "close": 100.0 + i,
             "volume": 100.0, "quote_volume": 1e4} for i in range(200)]

    class FakeClient:
        def klines_paginated(self, symbol, interval, total_bars, throttle=0.0, **kw):
            if interval == "60m":
                return bars
            raise MexcError("HTF yok (test)")   # HTF → None (test basit kalsın)

    captured: dict = {}

    def fake_scan(klines, symbol, interval, **kw):
        captured.update(kw)
        def piv(i, price):
            return Pivot(index=i, time=bars[i]["open_time"], price=price, kind="L")
        s = Setup(symbol=symbol, interval=interval, pattern_name="Gartley",
                  direction="bull",
                  pivots={"X": piv(0, 100.0), "A": piv(2, 103.0), "B": piv(5, 101.0),
                          "C": piv(8, 104.0), "D": piv(10, 100.0)},
                  b_ratio=0.6, c_ratio=0.5, d_ratio=0.786, bc_proj=1.27,
                  cd_ab_ratio=1.0, ab_cd_equivalent=False,
                  prz_low=99.5, prz_high=100.5, prz_components=[("x", 100.0)],
                  entry=100.0, stop=98.0, tp1=104.0, tp2=106.0,
                  detected_at=bars[10]["open_time"])
        s.elenen = False
        return [s]

    entry_modes: list = []

    def fake_sim(setup, future, **kw):
        entry_modes.append(kw.get("entry_mode"))
        return SimOutcome("TP", entered_idx=0, entered_time=future[0]["open_time"],
                          exited_idx=1, exited_time=future[1]["open_time"],
                          entered_price=100.0)

    monkeypatch.setattr(runner, "scan_klines", fake_scan)
    monkeypatch.setattr(runner, "simulate_outcome", fake_sim)

    run_id = runner.run_lab(["BTCUSDT"], ["60m"], 200, store, FakeClient())
    assert run_id > 0
    assert captured.get("target_mode") == "rr1"         # tek 1:1 hedef (canlı)
    assert captured.get("include_abcd") is False         # --no-abcd (canlı)
    assert entry_modes and entry_modes[0] == "limit"     # örneklem limit (PRZ) girişten


def test_reset_karakter_wipes_lab_keeps_live(store: Store):
    """reset_karakter: karakter tablolarını + backtest-kaynaklı setup/lifecycle'ı
    siler; CANLI (source='live') veriye dokunmaz."""
    from terminal.karakter.simulator import SimOutcome

    # Lab koşumu + backtest örneklemi (setups + lifecycle source='backtest' üretir)
    s, _ = _gartley_setup()
    run_id = store.create_karakter_run(1_700_000_000_000, 1000, ["TEST"], ["60m"])
    store.add_karakter_sample(run_id, s, SimOutcome("TP", 0, 1, 1, 2, entered_price=s.entry))
    store.finish_karakter_run(run_id, 1)
    store.recompute_karakter_scores()

    # CANLI setup + lifecycle (source='live') — korunmalı
    live, _ = _gartley_setup()
    live.symbol = "LIVE"
    live_id = store.upsert_setup(live)
    store.upsert_lifecycle(setup_id=live_id, state="Aday",
                           state_changed_at=1_700_000_000_000, source="live")
    assert store.get_karakter_score("TEST", "60m", "Gartley", "all") is not None

    counts = store.reset_karakter()

    for t in ("karakter_runs", "karakter_samples", "karakter_scores"):
        assert store._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM setup_lifecycle WHERE source='backtest'").fetchone()[0] == 0
    # canlı setup + lifecycle korundu
    assert store._conn.execute(
        "SELECT COUNT(*) FROM setup_lifecycle WHERE setup_id=?", (live_id,)).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM setups WHERE id=?", (live_id,)).fetchone()[0] == 1
    assert counts["runs"] == 1 and counts["backtest_setups"] >= 1


def test_karakter_samples_for_returns_trades(store: Store):
    """provider.karakter_samples_for: bir kombinasyonun tekil trade'lerini döner."""
    from terminal.karakter.simulator import SimOutcome
    from terminal.ui.data_provider import DataProvider

    s, _ = _gartley_setup()
    run_id = store.create_karakter_run(1_700_000_000_000, 1000, ["TEST"], ["60m"])
    store.add_karakter_sample(run_id, s, SimOutcome("TP", 0, 1, 1, 2, entered_price=s.entry))
    store.add_karakter_sample(run_id, s, SimOutcome("STOP", 0, 1, 1, 2, entered_price=s.entry))

    prov = DataProvider(store)
    rows = prov.karakter_samples_for(s.symbol, s.interval, s.pattern_name, "all")
    assert len(rows) == 2
    assert {r["outcome"] for r in rows} == {"TP", "STOP"}
    assert all(("r" in r and "entry" in r and "tp1" in r) for r in rows)
    # run_id filtresi
    assert len(prov.karakter_samples_for(
        s.symbol, s.interval, s.pattern_name, "all", run_id=run_id)) == 2
    assert prov.karakter_samples_for(
        s.symbol, s.interval, s.pattern_name, "all", run_id=999999) == []
