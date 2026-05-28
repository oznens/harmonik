"""PaperEngine thread-safety + lifecycle senkron testleri.

Bug: paylaşılan Store ana thread'de oluşturulup worker thread'lerinden
çağrılınca SQLite `check_same_thread` hatası fırlatıyordu → canlı paper
aç/kapa sessizce başarısız oluyordu. Burada cross-thread kullanımın artık
çalıştığı ve lifecycle ile senkronizasyonun stale açık trade'leri kapattığı
doğrulanır.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.paper.engine import PaperEngine
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _seed(store: Store):
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    assert setups
    s = setups[0]
    return s, store.upsert_setup(s)


def test_open_trade_from_worker_thread(store: Store):
    """Store ana thread'de; engine başka thread'den çağrılıyor → patlamamalı."""
    s, sid = _seed(store)
    pe = PaperEngine(store)
    result: dict = {}

    def worker():
        try:
            result["trade"] = pe.open_trade(s, sid, s.detected_at)
        except Exception as e:  # check_same_thread olsaydı burada patlardı
            result["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert "err" not in result, result.get("err")
    assert result["trade"] is not None
    assert len(pe.open_positions()) == 1


def test_concurrent_opens_serialized(store: Store):
    """Aynı pariteden çok thread aynı anda açmaya çalışsa bile parite-başı-tek
    kuralı bozulmamalı (lock serileştirir) — tek açık pozisyon kalır."""
    s, sid = _seed(store)
    pe = PaperEngine(store)

    def worker():
        pe.open_trade(s, sid, s.detected_at)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(pe.open_positions()) == 1


def test_sync_closes_paper_when_lifecycle_terminal(store: Store):
    s, sid = _seed(store)
    pe = PaperEngine(store)
    pe.open_trade(s, sid, s.detected_at)
    assert len(pe.open_positions()) == 1

    # Lifecycle STOP oldu ama close_trade KAÇTI (canlı tik hatası senaryosu)
    store.upsert_lifecycle(sid, "STOP", state_changed_at=s.detected_at + 1,
                           exited_at=s.detected_at + 1, exit_reason="stop")

    closed = pe.sync_closed_from_lifecycle()
    assert len(closed) == 1 and closed[0].outcome == "STOP"
    assert pe.open_positions() == []
    # idempotent: ikinci kez hiçbir şey kapatmaz
    assert pe.sync_closed_from_lifecycle() == []


def test_sync_keeps_open_when_lifecycle_active(store: Store):
    s, sid = _seed(store)
    pe = PaperEngine(store)
    pe.open_trade(s, sid, s.detected_at)
    store.upsert_lifecycle(sid, "Aktif", state_changed_at=s.detected_at,
                           entered_at=s.detected_at)

    assert pe.sync_closed_from_lifecycle() == []
    assert len(pe.open_positions()) == 1
