"""DataProvider testleri — UI'nin altındaki sorgu katmanı, saf Python."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.states import ADAY
from terminal.lifecycle.tracker import LifecycleTracker
from terminal.ui.data_provider import DataProvider
from tests.synthetic import (
    bat_bull, gartley_bull, make_xabcd_klines,
)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _seed_setup(store: Store, sentetic_fn, interval: str = "60m"):
    prices, kinds = sentetic_fn()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TESTUSDT", interval, zigzag_threshold=0.01, min_rr=0.0)
    if not setups:
        return None
    s = setups[0]
    sid = store.upsert_setup(s)
    return s, sid


def test_status_counts_empty(store: Store):
    p = DataProvider(store)
    sc = p.status_counts()
    assert sc.aktif == 0 and sc.aday == 0
    assert sc.tp == 0 and sc.stop == 0
    assert sc.toplam == 0
    assert sc.win_rate == 0.0


def test_status_counts_with_setups(store: Store):
    s, sid = _seed_setup(store, gartley_bull)
    tracker = LifecycleTracker("TESTUSDT", "60m", store)
    tracker.register_new(s, sid, aggressive_entry=False)

    p = DataProvider(store)
    sc = p.status_counts()
    assert sc.toplam == 1
    assert sc.aday == 1
    assert sc.aktif == 0
    assert sc.tp == 0


def test_setups_query_only_open(store: Store):
    s, sid = _seed_setup(store, gartley_bull)
    tracker = LifecycleTracker("TESTUSDT", "60m", store)
    tracker.register_new(s, sid, aggressive_entry=False)

    p = DataProvider(store)
    rows = p.setups(states=["Aday", "Aktif"])
    assert len(rows) == 1
    r = rows[0]
    assert r.state == "Aday"
    assert r.symbol == "TESTUSDT"
    assert r.pattern_name == "Gartley"
    assert r.direction == "bull"


def test_setups_filter_by_symbol(store: Store):
    _seed_setup(store, gartley_bull)
    _seed_setup(store, bat_bull)
    p = DataProvider(store)
    all_rows = p.setups()
    assert len(all_rows) == 2
    only_test = p.setups(symbol="TESTUSDT")
    assert len(only_test) == 2  # ikisi de TESTUSDT
    none_match = p.setups(symbol="NONEXISTENT")
    assert len(none_match) == 0


def test_karakter_scores_empty(store: Store):
    p = DataProvider(store)
    rows = p.karakter_scores()
    assert rows == []


def test_karakter_scores_after_lab(store: Store):
    from terminal.karakter.simulator import SimOutcome
    run_id = store.create_karakter_run(1_700_000_000_000, 100, ["TEST"], ["60m"])
    s, _ = _seed_setup(store, gartley_bull)
    for _ in range(5):
        store.add_karakter_sample(run_id, s, SimOutcome("TP", 0, 1, 1, 2))
    store.add_karakter_sample(run_id, s, SimOutcome("STOP", 0, 1, 1, 2))
    store.recompute_karakter_scores()

    p = DataProvider(store)
    rows = p.karakter_scores(direction="all", min_samples=1)
    assert len(rows) >= 1
    r = rows[0]
    assert r.sample_count == 6
    assert r.tp_count == 5
    assert r.stop_count == 1
    assert 0.8 < r.win_rate < 0.9


def test_setups_has_open_paper_flag(store: Store):
    from terminal.paper.engine import PaperEngine

    s, sid = _seed_setup(store, gartley_bull)
    LifecycleTracker("TESTUSDT", "60m", store).register_new(s, sid, aggressive_entry=True)
    pe = PaperEngine(store)

    p = DataProvider(store)
    # Henüz paper açılmadı → işaret yok
    assert all(not r.has_open_paper for r in p.setups())

    trade = pe.open_trade(s, sid, s.detected_at)
    assert trade is not None
    row = next(r for r in p.setups() if r.id == sid)
    assert row.has_open_paper is True

    # Kapanınca işaret kalkar
    pe.close_trade(sid, "TP", s.tp1, s.detected_at + 1)
    row = next(r for r in p.setups() if r.id == sid)
    assert row.has_open_paper is False


def test_setups_without_paper_table_ok(store: Store):
    # PaperEngine hiç oluşturulmadı → paper_trades tablosu yok; patlamamalı
    s, sid = _seed_setup(store, gartley_bull)
    rows = DataProvider(store).setups()
    assert rows and all(not r.has_open_paper for r in rows)
