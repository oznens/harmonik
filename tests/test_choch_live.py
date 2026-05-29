"""Canlı CHoCH bekleme kuyruğu: onay yoksa parka al, oluşunca aç (#3 canlı)."""
from __future__ import annotations

import types

from terminal.cli.run_live_multi import CHOCH_WAIT_BARS, PairWorker
from terminal.lifecycle.states import AKTIF, STOP


def _setup(d_time=1000, entry=100.0):
    piv = {"D": types.SimpleNamespace(time=d_time, price=entry)}
    return types.SimpleNamespace(pivots=piv, pattern_name="Bat",
                                 direction="bull", entry=entry)


class _Paper:
    def __init__(self):
        self.opened = []

    def open_trade(self, setup, sid, t, entry_price=None):
        self.opened.append((sid, entry_price))
        return types.SimpleNamespace(entry_price=entry_price, position_usd=20,
                                     leverage=5, risk_usd=20)


def _worker(entry_mode="market", choch_ok=True, state=AKTIF, age_bars=1):
    w = PairWorker(symbol="T", interval="60m", tg=None, min_q=0, min_karakter=0.0,
                   min_confluence=0, include_elenen=True, no_chart=True,
                   no_potential=True, use_htf=False, zigzag_threshold=0.01,
                   ltf_choch=True, paper_entry_mode=entry_mode)
    w.paper = _Paper()
    interval_ms = 3_600_000
    d_time = 1000
    latest_time = d_time + age_bars * interval_ms
    w.poller = types.SimpleNamespace(buffer=types.SimpleNamespace(
        latest={"open_time": latest_time, "open": 101.0}))
    w.tracker = types.SimpleNamespace(_interval_ms=lambda: interval_ms)
    w.store = types.SimpleNamespace(get_lifecycle=lambda sid: {"state": state})
    w._choch_confirmed = lambda setup: choch_ok
    w._pending_choch = {7: _setup(d_time=d_time)}
    return w


def test_pending_choch_market_confirm_queues_entry():
    w = _worker(entry_mode="market", choch_ok=True)
    w._check_pending_choch()
    assert 7 in w._pending_entries          # market: sonraki bar dolumu için kuyruğa
    assert 7 not in w._pending_choch
    assert w.paper.opened == []             # henüz açılmadı (sonraki barda dolar)


def test_pending_choch_limit_confirm_opens_at_entry():
    w = _worker(entry_mode="limit", choch_ok=True)
    w._check_pending_choch()
    assert w.paper.opened == [(7, 100.0)]   # limit: TAM entry'den açıldı
    assert 7 not in w._pending_choch


def test_pending_choch_not_confirmed_keeps_waiting():
    w = _worker(choch_ok=False)
    w._check_pending_choch()
    assert 7 in w._pending_choch            # onay yok → beklemeye devam
    assert w.paper.opened == []


def test_pending_choch_dropped_when_lifecycle_closed():
    w = _worker(choch_ok=True, state=STOP)
    w._check_pending_choch()
    assert 7 not in w._pending_choch        # stop oldu → vazgeç
    assert w.paper.opened == []


def test_pending_choch_dropped_on_timeout():
    w = _worker(choch_ok=False, age_bars=CHOCH_WAIT_BARS + 1)
    w._check_pending_choch()
    assert 7 not in w._pending_choch        # çok bekledi → vazgeç
