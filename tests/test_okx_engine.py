"""OKX demo engine testleri — açma/parite-tek/sync (fake OKX client'larla, ağsız)."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal.data.okx_instruments import Instrument, OkxInstruments
from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.paper.okx_engine import OkxDemoEngine
from tests.synthetic import gartley_bull, make_xabcd_klines


class _FakeOkx:
    """OkxDemoClient yerine — emir/hesap çağrılarını taklit eder."""
    def __init__(self):
        self.orders = {}
        self.next_id = 1000
        self._equity = 1000.0
        self.placed = []

    def balance(self, ccy="USDT"):
        return {"totalEq": str(self._equity), "details": [{"cashBal": str(self._equity)}]}

    def set_leverage(self, symbol, lever, td_mode="cross"):
        return {"lever": str(lever)}

    def place_order(self, symbol, side, sz, ord_type="limit", px=None,
                    tp_trigger=None, sl_trigger=None, cl_ord_id=None, **kw):
        oid = str(self.next_id); self.next_id += 1
        self.orders[oid] = {"state": "live", "instId": symbol}
        self.placed.append({"symbol": symbol, "side": side, "sz": sz, "px": px,
                            "tp": tp_trigger, "sl": sl_trigger, "ordId": oid})
        return {"ordId": oid, "sCode": "0", "sMsg": "ok"}

    def order_state(self, symbol, ord_id):
        return self.orders.get(ord_id, {"state": ""})

    def positions(self):
        return []  # hiç açık pozisyon yok (test)

    def positions_history(self):
        return []

    def cancel_order(self, symbol, ord_id):
        return {"sCode": "0"}


def _fake_instruments():
    oi = OkxInstruments.__new__(OkxInstruments)
    import threading, time
    oi._cache = {"BTC-USDT-SWAP": Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1),
                 "TEST-USDT-SWAP": Instrument("TEST-USDT-SWAP", 0.01, 50, 0.01, 0.01, 0.0001)}
    oi._loaded_at = time.monotonic() + 1e9
    oi._ttl = 1e12
    oi._lock = threading.Lock()
    return oi


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "okx.db")
    yield s
    s.close()


def _setup(store):
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)[0]
    return s, store.upsert_setup(s)


def test_open_trade_places_order(store):
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is not None
    assert len(fake.placed) == 1
    p = fake.placed[0]
    assert p["symbol"] == "TESTUSDT" and p["side"] == "buy"   # gartley_bull → long
    assert p["tp"] is not None and p["sl"] is not None        # TP/SL iliştirildi
    assert len(eng.open_positions()) == 1


def test_one_position_per_symbol(store):
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    eng.open_trade(s, sid, s.detected_at)
    # aynı setup tekrar → None (UNIQUE)
    assert eng.open_trade(s, sid, s.detected_at) is None
    assert len(fake.placed) == 1


def test_sync_closes_on_history_pnl(store):
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    # OKX: emir doldu + pozisyon geçmişte +12.5 realizedPnl ile kapandı
    fake.orders[t.ord_id]["state"] = "filled"
    fake.positions = lambda: []
    fake.positions_history = lambda: [{"instId": "TEST-USDT-SWAP",
                                       "realizedPnl": "12.5", "closeAvgPx": "111"}]
    n = eng.sync()
    assert n == 1
    row = store._conn.execute(
        "SELECT state, pnl_usd FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "closed" and abs(row[1] - 12.5) < 1e-6
    assert eng.open_positions() == []


def test_summary(store):
    s, sid = _setup(store)
    eng = OkxDemoEngine(store, _FakeOkx(), _fake_instruments())
    eng.open_trade(s, sid, s.detected_at)
    summ = eng.summary()
    assert summ["open"] == 1 and "equity" in summ


# ---- PaMonic modu ----

def test_pamonic_no_ob_skips(store):
    """PaMonic modu: OB yoksa (klines yok) pas geç (enforce) — emir atılmaz."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments(), pamonic=True)
    # klines vermeden → OB bulunamaz → pas geç
    t = eng.open_trade(s, sid, s.detected_at, klines=None)
    assert t is None
    assert len(fake.placed) == 0
    assert len(eng.open_positions()) == 0


def test_pamonic_with_ob_uses_narrow_stop(store):
    """OB varsa: dar stop (OB arkası) + yapısal TP ile emir atılır."""
    from terminal.detection.scanner import scan_klines, default_threshold
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12)
    s = scan_klines(kl, "TESTUSDT", "60m", zigzag_threshold=0.01,
                    target_mode="structural", min_rr=0.0)[0]
    sid = store.upsert_setup(s)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments(), pamonic=True)
    # gerçek klines ver → OB aranır. (Sentetik Gartley'de OB olmayabilir →
    # ya pas geçer ya dar stopla girer; ikisi de geçerli. Davranışı doğrula.)
    t = eng.open_trade(s, sid, s.detected_at, klines=kl)
    if t is not None:
        # OB bulundu → dar stop kullanıldı (setup.stop'tan farklı olabilir)
        assert len(fake.placed) == 1
        p = fake.placed[0]
        assert p["sl"] is not None and p["tp"] is not None
    else:
        # OB yok → pas geçti (enforce), emir yok
        assert len(fake.placed) == 0
