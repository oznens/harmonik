"""LifecycleTracker.reconcile() testleri.

reconcile, bootstrap sonrası açık (Aday/Aktif) setup'ları tampondaki tüm
mumlar üzerinden yeniden değerlendirir. Amaç: süreç kapalıyken (restart/
deploy/MEXC kesintisi) advance()'in tek-mum kontrolünden kaçan STOP/TP'leri
yakalamak — LTC gibi yanlış "Aktif" kalmaları engellemek.

Önemli kural:
  - Çıkış geçişleri (TP/STOP/ZI/EO) on_transition'a İLETİLİR (paper kapatma).
  - Giriş geçişleri (ADAY→AKTIF) restart spam'ini önlemek için SUSTURULUR,
    ama lifecycle durumu yine de güncellenir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.states import ADAY, AKTIF, STOP, TP
from terminal.lifecycle.tracker import LifecycleTracker, Transition
from tests.synthetic import gartley_bull, make_xabcd_klines

SYMBOL = "TESTUSDT"
INTERVAL = "60m"
INTERVAL_MS = 3_600_000


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _bull_setup(store: Store):
    """Bir bull setup üret + DB'ye yaz. (entry≈104.28, stop=100, tp1≈107.6)"""
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12,
                               base_time=1_700_000_000_000)
    setups = scan_klines(klines, SYMBOL, INTERVAL, zigzag_threshold=0.01, min_rr=0.0)
    assert setups
    s = setups[0]
    assert s.direction == "bull"
    sid = store.upsert_setup(s)
    return s, sid, klines


def _bar(t: int, hi: float, lo: float) -> dict:
    return {"open_time": t, "close_time": t + INTERVAL_MS - 1,
            "open": (hi + lo) / 2, "high": hi, "low": lo,
            "close": (hi + lo) / 2, "volume": 100.0, "quote_volume": 1000.0}


def _capture():
    seen: list[Transition] = []
    return seen, (lambda t: seen.append(t))


def test_reconcile_catches_missed_stop(store: Store):
    s, sid, klines = _bull_setup(store)
    entered = klines[-1]["open_time"]
    # Setup AKTIF — ama advance() kaçırmış gibi düşün (backfill yapılmadı)
    store.upsert_lifecycle(sid, AKTIF, state_changed_at=entered, entered_at=entered)
    # Girişten sonra fiyat stop'un altına iner (low <= 100)
    breach = [_bar(entered + INTERVAL_MS, hi=103.0, lo=98.0)]

    seen, cb = _capture()
    tr = LifecycleTracker(SYMBOL, INTERVAL, store, on_transition=cb)
    trans = tr.reconcile(klines + breach)

    assert len(trans) == 1 and trans[0].new_state == STOP
    assert store.get_lifecycle(sid)["state"] == STOP
    # Çıkış geçişi paper'a/bildirime iletilmeli
    assert [t.new_state for t in seen] == [STOP]


def test_reconcile_catches_missed_tp(store: Store):
    s, sid, klines = _bull_setup(store)
    entered = klines[-1]["open_time"]
    store.upsert_lifecycle(sid, AKTIF, state_changed_at=entered, entered_at=entered)
    breach = [_bar(entered + INTERVAL_MS, hi=109.0, lo=104.5)]  # high >= tp1≈107.6

    seen, cb = _capture()
    tr = LifecycleTracker(SYMBOL, INTERVAL, store, on_transition=cb)
    trans = tr.reconcile(klines + breach)

    assert len(trans) == 1 and trans[0].new_state == TP
    assert store.get_lifecycle(sid)["state"] == TP
    assert [t.new_state for t in seen] == [TP]


def test_reconcile_leaves_active_when_no_breach(store: Store):
    s, sid, klines = _bull_setup(store)
    entered = klines[-1]["open_time"]
    store.upsert_lifecycle(sid, AKTIF, state_changed_at=entered, entered_at=entered)
    # Fiyat stop ile tp1 arasında kalır → tetik yok
    calm = [_bar(entered + INTERVAL_MS, hi=106.0, lo=103.0),
            _bar(entered + 2 * INTERVAL_MS, hi=105.5, lo=102.5)]

    seen, cb = _capture()
    tr = LifecycleTracker(SYMBOL, INTERVAL, store, on_transition=cb)
    trans = tr.reconcile(klines + calm)

    assert trans == []
    assert store.get_lifecycle(sid)["state"] == AKTIF
    assert seen == []


def test_reconcile_idempotent(store: Store):
    s, sid, klines = _bull_setup(store)
    entered = klines[-1]["open_time"]
    store.upsert_lifecycle(sid, AKTIF, state_changed_at=entered, entered_at=entered)
    full = klines + [_bar(entered + INTERVAL_MS, hi=103.0, lo=98.0)]

    tr = LifecycleTracker(SYMBOL, INTERVAL, store, on_transition=None)
    assert len(tr.reconcile(full)) == 1
    # İkinci kez: setup artık terminal (STOP) → açık değil → hiçbir şey yapma
    assert tr.reconcile(full) == []
    assert store.get_lifecycle(sid)["state"] == STOP


def test_reconcile_suppresses_entry_emit_but_emits_exit(store: Store):
    """ADAY iken downtime'da entry tetiklenip stop olduysa: DB STOP olur,
    ama on_transition'a SADECE STOP gider (ADAY→AKTIF kartı/işlemi susar)."""
    s, sid, klines = _bull_setup(store)
    d_time = s.pivots["D"].time
    store.upsert_lifecycle(sid, ADAY, state_changed_at=d_time)
    # 1) entry tetikleyen bar (low <= entry 104.28) 2) stop kıran bar (low <= 100)
    seq = [_bar(d_time + INTERVAL_MS, hi=105.0, lo=104.0),
           _bar(d_time + 2 * INTERVAL_MS, hi=103.0, lo=98.0)]

    seen, cb = _capture()
    tr = LifecycleTracker(SYMBOL, INTERVAL, store, on_transition=cb)
    trans = tr.reconcile(klines + seq)

    # reconcile içsel olarak iki geçiş uyguladı (AKTIF + STOP)
    assert [t.new_state for t in trans] == [AKTIF, STOP]
    # ama dışa SADECE çıkış (STOP) yayıldı — giriş susturuldu
    assert [t.new_state for t in seen] == [STOP]
    assert store.get_lifecycle(sid)["state"] == STOP
