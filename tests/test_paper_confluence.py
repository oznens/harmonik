"""--paper-min-confluence: paper'a sadece confluence >= eşik setupları açılır.

Veri (39-43 işlem): confluence <50 zarar, 50-69 edge. Bu filtre düşük-skorlu
setupları paper defterine sokmaz (lifecycle yine takip eder).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.cli.run_live_multi import PairWorker
from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.tracker import Transition
from terminal.paper.engine import PaperEngine
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "t.db")
    yield s
    s.close()


def _worker(store: Store, pe: PaperEngine, threshold: int) -> PairWorker:
    w = PairWorker(
        symbol="TESTUSDT", interval="60m", tg=None, min_q=0, min_karakter=0.0,
        min_confluence=0, include_elenen=False, no_chart=True, no_potential=True,
        use_htf=False, zigzag_threshold=0.01, paper_engine=pe,
        paper_min_confluence=threshold,
    )
    w.store = store
    w.poller = None      # freshness kapısı atlanır (latest=None)
    w.tracker = None
    return w


def _setup(store: Store, conf: int):
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)[0]
    s.confluence_score = conf
    return s, store.upsert_setup(s)


def _aktif(s, sid):
    return Transition(s, "Aday", "Aktif", s.entry, s.detected_at, setup_id=sid)


def test_low_confluence_filtered_from_paper(store: Store):
    pe = PaperEngine(store)
    w = _worker(store, pe, threshold=50)
    s, sid = _setup(store, conf=40)           # eşiğin altında
    w._on_transition(_aktif(s, sid))
    assert sid not in w._pending_entries       # paper'a kuyruğa alınmadı


def test_high_confluence_allowed_to_paper(store: Store):
    pe = PaperEngine(store)
    w = _worker(store, pe, threshold=50)
    s, sid = _setup(store, conf=60)           # eşikte/üstünde
    w._on_transition(_aktif(s, sid))
    assert sid in w._pending_entries           # paper'a kuyruğa alındı


def test_filter_off_allows_all(store: Store):
    pe = PaperEngine(store)
    w = _worker(store, pe, threshold=0)        # filtre kapalı
    s, sid = _setup(store, conf=5)            # çok düşük
    w._on_transition(_aktif(s, sid))
    assert sid in w._pending_entries           # filtre yok → kuyruğa alındı
