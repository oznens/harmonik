"""TP/STOP Telegram bildirimi kapsamı: paper modunda yalnızca gerçekten paper
pozisyonu kapanan coinler bildirilir (Telegram = dashboard)."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.cli.run_live_multi import PairWorker
from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.tracker import Transition
from terminal.paper.engine import PaperEngine
from tests.synthetic import bat_bull, gartley_bull, make_xabcd_klines


class FakeTg:
    def __init__(self):
        self.messages = []
        self.photos = []

    def send_message(self, msg, **kw):
        self.messages.append(msg)

    def send_photo(self, *a, **kw):
        self.photos.append(a)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _seed(store: Store, fn, base_time: int):
    prices, kinds = fn()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=base_time)
    setups = scan_klines(klines, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    assert setups
    s = setups[0]
    return s, store.upsert_setup(s)


def _worker(store: Store, pe: PaperEngine, tg: FakeTg) -> PairWorker:
    w = PairWorker(
        symbol="TESTUSDT", interval="60m", tg=tg,
        min_q=0, min_karakter=0.0, min_confluence=0,
        include_elenen=False, no_chart=True, no_potential=True,
        use_htf=False, zigzag_threshold=0.01, paper_engine=pe,
    )
    w.store = store
    w.poller = None
    return w


def test_exit_notifies_when_paper_position_closed(store: Store):
    s, sid = _seed(store, gartley_bull, 1_700_000_000_000)
    pe = PaperEngine(store)
    pe.open_trade(s, sid, s.detected_at)  # paper pozisyonu var
    tg = FakeTg()
    w = _worker(store, pe, tg)

    t = Transition(s, "Aktif", "STOP", s.stop, s.detected_at + 1, setup_id=sid)
    w._on_transition(t)

    assert len(tg.messages) == 1          # bildirildi
    assert "STOP" in tg.messages[0]
    assert pe.open_positions() == []      # paper kapandı


def test_exit_silent_when_no_paper_position(store: Store):
    # Paper pozisyonu AÇILMAMIŞ bir setup STOP olursa → Telegram'a gitmez
    s, sid = _seed(store, bat_bull, 1_700_100_000_000)
    pe = PaperEngine(store)  # bu setup için open_trade çağrılmadı
    tg = FakeTg()
    w = _worker(store, pe, tg)

    t = Transition(s, "Aktif", "STOP", s.stop, s.detected_at + 1, setup_id=sid)
    w._on_transition(t)

    assert tg.messages == []   # paper yok → bildirim yok
