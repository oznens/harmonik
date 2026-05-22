"""Lifecycle state machine testleri."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.states import ADAY, AKTIF, EO, STOP, TP
from terminal.lifecycle.tracker import LifecycleTracker
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _bullish_setup_in_db(store: Store):
    """Sentetik bull Gartley üret → tara → DB'ye yaz; (setup, id) döner."""
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TEST", "60m", zigzag_threshold=0.01)
    s = next(x for x in setups if x.pattern_name == "Gartley" and x.direction == "bull")
    sid = store.upsert_setup(s)
    return s, sid, klines


def test_register_new_creates_aday(store: Store):
    s, sid, _ = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store)
    tracker.register_new(s, sid)
    row = store.get_lifecycle(sid)
    assert row is not None
    assert row["state"] == ADAY


def test_aday_to_aktif_on_entry_touch(store: Store):
    s, sid, klines = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store)
    tracker.register_new(s, sid)

    # Bull: fiyat entry seviyesine değdiğinde Aktif. D pivot'tan sonra bir mum
    # üretelim ki low = entry'ye eşit/altında olsun.
    last_t = klines[-1]["open_time"] + 3_600_000
    trigger_bar = {
        "open_time": last_t, "close_time": last_t + 3_599_999,
        "open": s.entry + 0.5, "high": s.entry + 0.5,
        "low": s.entry - 0.01,  # entry'ye değdi
        "close": s.entry, "volume": 100, "quote_volume": 1000,
    }
    transitions = tracker.advance(klines + [trigger_bar])
    assert len(transitions) == 1
    assert transitions[0].new_state == AKTIF
    assert store.get_lifecycle(sid)["state"] == AKTIF


def test_aktif_to_tp_on_high_touch(store: Store):
    s, sid, klines = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store)
    tracker.register_new(s, sid)

    # 1) Önce Aday → Aktif
    last_t = klines[-1]["open_time"] + 3_600_000
    trigger_bar = {
        "open_time": last_t, "close_time": last_t + 3_599_999,
        "open": s.entry, "high": s.entry, "low": s.entry - 0.01,
        "close": s.entry, "volume": 100, "quote_volume": 1000,
    }
    tracker.advance(klines + [trigger_bar])
    assert store.get_lifecycle(sid)["state"] == AKTIF

    # 2) Sonra Aktif → TP: high ≥ tp1
    last_t += 3_600_000
    tp_bar = {
        "open_time": last_t, "close_time": last_t + 3_599_999,
        "open": s.entry, "high": s.tp1 + 0.1,
        "low": s.entry - 0.01, "close": s.tp1,
        "volume": 100, "quote_volume": 1000,
    }
    transitions = tracker.advance(klines + [trigger_bar, tp_bar])
    assert any(t.new_state == TP for t in transitions)
    assert store.get_lifecycle(sid)["state"] == TP


def test_aktif_to_stop_on_low_break(store: Store):
    s, sid, klines = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store)
    tracker.register_new(s, sid)
    last_t = klines[-1]["open_time"] + 3_600_000

    # Önce Aktif yap
    trigger_bar = {
        "open_time": last_t, "close_time": last_t + 3_599_999,
        "open": s.entry, "high": s.entry, "low": s.entry - 0.01,
        "close": s.entry, "volume": 100, "quote_volume": 1000,
    }
    tracker.advance(klines + [trigger_bar])

    # Sonra SL kır: low < stop
    last_t += 3_600_000
    stop_bar = {
        "open_time": last_t, "close_time": last_t + 3_599_999,
        "open": s.entry - 0.5, "high": s.entry, "low": s.stop - 0.1,
        "close": s.stop - 0.05, "volume": 100, "quote_volume": 1000,
    }
    transitions = tracker.advance(klines + [trigger_bar, stop_bar])
    assert any(t.new_state == STOP for t in transitions)
    assert store.get_lifecycle(sid)["state"] == STOP


def test_aday_to_eo_on_timeout(store: Store):
    s, sid, klines = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store,
                                aday_bars_timeout=5)  # küçük timeout — test için
    tracker.register_new(s, sid)

    # 6 mum, hiçbiri entry'ye değmiyor → EO
    timeout_klines = list(klines)
    last_t = klines[-1]["open_time"]
    for i in range(6):
        last_t += 3_600_000
        timeout_klines.append({
            "open_time": last_t, "close_time": last_t + 3_599_999,
            "open": s.entry + 100, "high": s.entry + 101,
            "low": s.entry + 99, "close": s.entry + 100,
            "volume": 100, "quote_volume": 1000,
        })

    transitions = tracker.advance(timeout_klines)
    assert any(t.new_state == EO for t in transitions)
    assert store.get_lifecycle(sid)["state"] == EO


def test_no_double_register(store: Store):
    s, sid, _ = _bullish_setup_in_db(store)
    tracker = LifecycleTracker("TEST", "60m", store)
    tracker.register_new(s, sid)
    tracker.register_new(s, sid)  # idempotent
    # Tek lifecycle satırı, tek "aday tespit" eventi olmalı
    cur = store._conn.execute("SELECT COUNT(*) FROM setup_events WHERE setup_id = ?", (sid,))
    assert cur.fetchone()[0] == 1
