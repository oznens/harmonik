"""Kapanmış trade grafiği: pencere ÇIKIŞ anına kadar uzar + işaret.

Web tarafı (`_klines_for_setup`, `_lifecycle_exit`) ve render_setup_chart'ın
exit_marker ile PNG üretmesi test edilir. (Masaüstü chart_window PySide6
gerektirdiğinden burada import edilmez; aynı _window_bounds mantığını paylaşır.)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.telegram_bot.charts import render_setup_chart
from terminal.web import server
from tests.synthetic import gartley_bull, make_xabcd_klines

MS = 3_600_000


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _setup_with_tail(store: Store, n_after_d: int = 60):
    """Pattern + D sonrası düz mumlar (çıkış senaryosu için)."""
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)  # 49 bar, son = D
    setups = scan_klines(kl, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    assert setups
    s = setups[0]
    last = kl[-1]
    price = last["close"]
    for i in range(1, n_after_d + 1):
        t = last["open_time"] + i * MS
        kl.append({"open_time": t, "close_time": t + MS - 1, "open": price,
                   "high": price * 1.001, "low": price * 0.999, "close": price,
                   "volume": 100.0, "quote_volume": 1000.0})
    store.upsert_klines("TESTUSDT", "60m", kl)
    sid = store.upsert_setup(s)
    return s, sid


def test_window_extends_to_exit(store: Store):
    s, _sid = _setup_with_tail(store, n_after_d=60)
    d_time = s.pivots["D"].time

    no_exit = server._klines_for_setup(store._conn, s)
    exit_t = d_time + 55 * MS
    with_exit = server._klines_for_setup(store._conn, s, exit_time=exit_t)

    # Çıkışlı pencere daha ileriye uzar ve çıkış barını kapsar
    assert with_exit[-1]["open_time"] > no_exit[-1]["open_time"]
    assert with_exit[-1]["open_time"] >= exit_t


def test_lifecycle_exit_lookup(store: Store):
    s, sid = _setup_with_tail(store, n_after_d=5)
    # Açık → None
    store.upsert_lifecycle(sid, "Aktif", state_changed_at=s.detected_at,
                           entered_at=s.detected_at)
    assert server._lifecycle_exit(store._conn, sid) is None
    # STOP → (exit_time, "STOP")
    ex = s.pivots["D"].time + 3 * MS
    store.upsert_lifecycle(sid, "STOP", state_changed_at=ex, exited_at=ex,
                           exit_reason="stop")
    assert server._lifecycle_exit(store._conn, sid) == (ex, "STOP")


def test_render_with_exit_marker_png(store: Store):
    s, _sid = _setup_with_tail(store, n_after_d=60)
    exit_t = s.pivots["D"].time + 40 * MS
    klines = server._klines_for_setup(store._conn, s, exit_time=exit_t)
    png = render_setup_chart(s, klines, exit_marker=(exit_t, "STOP"))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # geçerli PNG, çökmeden üretildi
