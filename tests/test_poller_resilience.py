"""Poller dayanıklılığı + HTF zaman-cache: rate-limit (510) worker'ı öldürmesin.

Bug: poll_once yalnızca MexcError (spot) yakalıyordu; --futures'ta gelen
MexcFuturesError yakalanmayıp worker thread'ini öldürüyordu. Ayrıca HTF her bar
çekiliyordu (gereksiz istek → 510). Burada ikisi de doğrulanır.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.data.kline_poller import KlinePoller
from terminal.data.mexc_futures import MexcFuturesError
from terminal.db.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "t.db")
    yield s
    s.close()


class _FuturesRateLimitClient:
    """klines() her zaman MEXC 510 (futures) fırlatır."""
    def klines(self, *a, **kw):
        raise MexcFuturesError(
            "futures API: {'code': 510, 'message': 'Requests are too frequent'}")


class _BoomClient:
    def klines(self, *a, **kw):
        raise RuntimeError("beklenmedik")


def test_poll_once_survives_futures_rate_limit(store: Store):
    p = KlinePoller("BTCUSDT", "60m", _FuturesRateLimitClient(), store, on_closed=None)
    # Patlamamalı, worker ölmemeli — sadece 0 döner
    assert p.poll_once() == 0


def test_poll_once_survives_unexpected_error(store: Store):
    p = KlinePoller("BTCUSDT", "60m", _BoomClient(), store, on_closed=None)
    assert p.poll_once() == 0


def test_htf_time_cache_limits_requests(store: Store):
    from terminal.cli.run_live_multi import PairWorker

    class _CountingClient:
        def __init__(self):
            self.calls = 0

        def klines(self, *a, **kw):
            self.calls += 1
            return [{"open_time": 1, "high": 1, "low": 1, "open": 1,
                     "close": 1, "volume": 1, "quote_volume": 1}]

    w = PairWorker(
        symbol="BTCUSDT", interval="60m", tg=None,
        min_q=0, min_karakter=0.0, min_confluence=0, include_elenen=False,
        no_chart=True, no_potential=True, use_htf=True, zigzag_threshold=0.01,
    )
    assert w.htf_interval is not None  # 60m → bir HTF aralığı var
    w.client = _CountingClient()

    w._fetch_htf()
    w._fetch_htf()
    w._fetch_htf()
    # Zaman-cache: arka arkaya çağrılar tek istekle karşılanır
    assert w.client.calls == 1


def test_futures_global_throttle_spaces_requests(monkeypatch):
    """Global hız sınırı: ardışık istekler min aralıkla serileşir."""
    import time

    import terminal.data.mexc_futures as mf
    monkeypatch.setattr(mf, "_MIN_REQUEST_INTERVAL", 0.05)
    mf.MexcFuturesClient._last_request_ts = 0.0

    t0 = time.monotonic()
    for _ in range(5):
        mf.MexcFuturesClient._throttle()
    elapsed = time.monotonic() - t0
    # 5 çağrı → en az ~4 aralık (0.05×4=0.2s); toleranslı alt sınır
    assert elapsed >= 0.05 * 4 * 0.8
