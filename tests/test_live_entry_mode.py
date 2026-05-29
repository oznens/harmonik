"""Canlı giriş modu: 'limit' → entry fiyatından AÇ; 'market' → sonraki bara ertele."""
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


def _worker(store: Store, pe: PaperEngine, mode: str) -> PairWorker:
    w = PairWorker(
        symbol="TESTUSDT", interval="60m", tg=None, min_q=0, min_karakter=0.0,
        min_confluence=0, include_elenen=False, no_chart=True, no_potential=True,
        use_htf=False, zigzag_threshold=0.01, paper_engine=pe,
        paper_entry_mode=mode,
    )
    w.store = store
    w.poller = None
    w.tracker = None
    return w


def _setup(store: Store):
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)[0]
    return s, store.upsert_setup(s)


def _aktif(s, sid):
    # Pasif _check_aday AKTIF'i entry fiyatıyla tetikler (trigger_price=entry)
    return Transition(s, "Aday", "Aktif", s.entry, s.detected_at, setup_id=sid)


def test_limit_mode_opens_at_entry_price(store: Store):
    s, sid = _setup(store)
    pe = PaperEngine(store)
    w = _worker(store, pe, mode="limit")

    w._on_transition(_aktif(s, sid))

    assert sid not in w._pending_entries          # pending YOK — anında açıldı
    opens = pe.open_positions()
    assert len(opens) == 1
    assert opens[0]["entry"] == s.entry            # dolum = TAM entry (limit, slippage yok)


def test_market_mode_defers_to_next_bar(store: Store):
    s, sid = _setup(store)
    pe = PaperEngine(store)
    w = _worker(store, pe, mode="market")

    w._on_transition(_aktif(s, sid))

    assert sid in w._pending_entries               # market → sonraki bar dolumu (pending)
    assert pe.open_positions() == []               # henüz açılmadı
