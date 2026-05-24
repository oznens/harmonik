"""Outcome override (manuel düzeltme) testleri."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.tracker import LifecycleTracker
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _seed_setup(store: Store) -> int:
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    setups = scan_klines(klines, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == "Gartley")
    sid = store.upsert_setup(s)
    tracker = LifecycleTracker("TESTUSDT", "60m", store)
    tracker.register_new(s, sid)
    return sid


def test_override_eo_to_tp(store: Store):
    sid = _seed_setup(store)
    # Önce sahte bir EO state oluştur
    store.upsert_lifecycle(setup_id=sid, state="EO", state_changed_at=1, exited_at=1)
    assert store.get_lifecycle(sid)["state"] == "EO"

    store.override_outcome(sid, "TP", reason="grafik doğrulandı")

    assert store.get_lifecycle(sid)["state"] == "TP"
    overrides = store.get_overrides(sid)
    assert len(overrides) == 1
    assert overrides[0]["original_state"] == "EO"
    assert overrides[0]["override_state"] == "TP"
    assert overrides[0]["reason"] == "grafik doğrulandı"


def test_override_creates_audit_event(store: Store):
    sid = _seed_setup(store)
    store.upsert_lifecycle(setup_id=sid, state="STOP", state_changed_at=1, exited_at=1)

    store.override_outcome(sid, "TP", reason="yanlış SL")

    # setup_events tablosunda manuel düzeltme kaydı olmalı
    cur = store._conn.execute(
        """SELECT * FROM setup_events WHERE setup_id = ? AND new_state = 'TP'
           ORDER BY event_time DESC LIMIT 1""",
        (sid,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["prev_state"] == "STOP"
    assert "manuel" in row["notes"].lower()


def test_override_noop_when_same_state(store: Store):
    sid = _seed_setup(store)
    store.upsert_lifecycle(setup_id=sid, state="TP", state_changed_at=1, exited_at=1)
    store.override_outcome(sid, "TP", reason="x")  # aynı state
    # Override kaydı YAZILMAMALI
    assert store.count_overrides() == 0


def test_multiple_overrides_history(store: Store):
    sid = _seed_setup(store)
    store.upsert_lifecycle(setup_id=sid, state="EO", state_changed_at=1, exited_at=1)
    store.override_outcome(sid, "TP", reason="ilk düzeltme")
    store.override_outcome(sid, "STOP", reason="aslında STOP")
    store.override_outcome(sid, "TP", reason="tekrar TP")

    overrides = store.get_overrides(sid)
    assert len(overrides) == 3
    # En yenisi başta
    assert overrides[0]["override_state"] == "TP"
    assert overrides[0]["reason"] == "tekrar TP"
    # State güncel mi
    assert store.get_lifecycle(sid)["state"] == "TP"


def test_count_overrides(store: Store):
    sid1 = _seed_setup(store)
    store.upsert_lifecycle(setup_id=sid1, state="STOP", state_changed_at=1, exited_at=1)
    assert store.count_overrides() == 0
    store.override_outcome(sid1, "TP", reason="r1")
    assert store.count_overrides() == 1
    store.override_outcome(sid1, "EO", reason="r2")
    assert store.count_overrides() == 2
