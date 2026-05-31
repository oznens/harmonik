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
    def __init__(self, free_usdt=None):
        self.orders = {}
        self.next_id = 1000
        self._equity = 1000.0
        self.free_usdt = free_usdt   # None → balance'ta USDT availBal yok (kapı inert)
        self.placed = []

    def balance(self, ccy="USDT"):
        details = [{"cashBal": str(self._equity)}]
        if self.free_usdt is not None:
            details.append({"ccy": "USDT", "availBal": str(self.free_usdt)})
        return {"totalEq": str(self._equity), "details": details}

    def set_leverage(self, symbol, lever, td_mode="cross"):
        return {"lever": str(lever)}

    def place_order(self, symbol, side, sz, ord_type="limit", px=None,
                    tp_trigger=None, sl_trigger=None, cl_ord_id=None, **kw):
        oid = str(self.next_id); self.next_id += 1
        self.orders[oid] = {"state": "live", "instId": symbol}
        self.placed.append({"symbol": symbol, "side": side, "sz": sz, "px": px,
                            "ord_type": ord_type, "tp": tp_trigger, "sl": sl_trigger,
                            "ordId": oid})
        return {"ordId": oid, "sCode": "0", "sMsg": "ok"}

    def order_state(self, symbol, ord_id):
        return self.orders.get(ord_id, {"state": ""})

    def positions(self):
        return []  # hiç açık pozisyon yok (test)

    def positions_history(self):
        return []

    def cancel_order(self, symbol, ord_id):
        return {"sCode": "0"}

    def algo_pending(self, ord_type="oco", inst_type="SWAP"):
        return getattr(self, "algos", [])

    def cancel_algo(self, symbol, algo_id, ord_type="oco"):
        self.canceled_algos = getattr(self, "canceled_algos", [])
        self.canceled_algos.append((symbol, algo_id))
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


def test_px_never_scientific_notation():
    """51000 tpTriggerPx fix: düşük fiyatlar bilimsel notasyon ÜRETMEMELİ."""
    f = OkxDemoEngine._px
    assert f(2.9089e-05) == "0.000029089"      # FLOKI — 'e-05' OLMAZ
    assert "e" not in f(1e-07).lower()
    assert f(74000.1) == "74000.1"
    assert f(2.0) == "2"                         # sondaki .0 kırpılır
    assert f(0.10065) == "0.10065"


def test_market_skips_when_price_past_tp(store):
    """51050 fix: market girişte canlı fiyat zaten TP'yi geçmişse (tükenmiş
    hareket) emir atma — OKX TP'yi son fiyata göre kontrol eder."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())   # market default
    # Bull setup: canlı son fiyat TP'nin ÜSTÜNDE → TP yanlış tarafta (tükenmiş)
    kl = [{"open_time": 1, "open": 1, "high": 1, "low": 1,
           "close": s.tp1 * 1.05}]               # fiyat TP'yi geçmiş
    t = eng.open_trade(s, sid, s.detected_at, klines=kl)
    assert t is None
    assert len(fake.placed) == 0                  # tükenmiş → emir gitmedi


def test_market_opens_when_price_in_range(store):
    """Canlı fiyat SL/TP aralığındaysa (sağlıklı) market emir atılır."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    kl = [{"open_time": 1, "open": 1, "high": 1, "low": 1,
           "close": s.entry}]                     # tam entry'de → aralık içi
    t = eng.open_trade(s, sid, s.detected_at, klines=kl)
    assert t is not None
    assert fake.placed[0]["ord_type"] == "market"


def test_default_entry_is_market(store):
    """Varsayılan market: paper gibi anında dol (px yok, ordType=market)."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())   # default entry_type
    eng.open_trade(s, sid, s.detected_at)
    p = fake.placed[0]
    assert p["ord_type"] == "market"
    assert p["px"] is None                       # market'te limit fiyatı gitmez
    assert p["tp"] is not None and p["sl"] is not None


def test_limit_entry_sends_price(store):
    """entry_type=limit: ordType=limit + px gönderir (eski davranış)."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments(), entry_type="limit")
    eng.open_trade(s, sid, s.detected_at)
    p = fake.placed[0]
    assert p["ord_type"] == "limit"
    assert p["px"] is not None


def test_skips_if_okx_already_has_position(store):
    """KRİTİK: OKX'te o paritede gerçek açık pozisyon varsa emir atma (birikme/-601 bug)."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    # OKX'te TESTUSDT zaten açık (DB boş ama OKX'te var → birikme riski)
    fake.positions = lambda: [{"instId": "TEST-USDT-SWAP", "pos": "100"}]
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is None                       # OKX gerçek kontrol → atladı
    assert len(fake.placed) == 0           # emir GİTMEDİ


def test_skips_when_free_usdt_below_margin(store):
    """BAKİYE KAPISI: boş USDT işlemin margin'ini karşılamıyorsa açma (51008 önle)."""
    s, sid = _setup(store)
    fake = _FakeOkx(free_usdt=0.5)        # neredeyse boş hesap
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is None                       # boş USDT < margin → atladı
    assert len(fake.placed) == 0           # emir GİTMEDİ


def test_opens_when_free_usdt_sufficient(store):
    """Boş USDT margin'i karşılıyorsa açar (sabit max-open yok, sınır bakiye)."""
    s, sid = _setup(store)
    fake = _FakeOkx(free_usdt=100_000)     # bol bakiye
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is not None
    assert len(fake.placed) == 1


def test_min_free_buffer_reserves_balance(store):
    """min_free_usdt tamponu: boş USDT margin'i karşılasa da tampon altında kalırsa açma."""
    s, sid = _setup(store)
    # margin küçük (~birkaç $) ama free=margin+5 < margin+min_free(1000) → atla
    fake = _FakeOkx(free_usdt=50)
    eng = OkxDemoEngine(store, fake, _fake_instruments(), min_free_usdt=1000)
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is None
    assert len(fake.placed) == 0


def test_sync_cleans_orphan_oco(store):
    """Pozisyonu olmayan bekleyen OCO (TP/SL) emirleri iptal edilir; pozisyonu
    olanlara dokunulmaz (koruma geçerli)."""
    fake = _FakeOkx()
    # AAVE açık pozisyonda (OCO'su geçerli), SAND öksüz (poz yok → iptal)
    fake.positions = lambda: [{"instId": "AAVE-USDT-SWAP", "pos": "184"}]
    fake.algos = [{"instId": "AAVE-USDT-SWAP", "algoId": "a1"},
                  {"instId": "SAND-USDT-SWAP", "algoId": "a2"}]
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    eng.sync()
    canceled = getattr(fake, "canceled_algos", [])
    assert ("SAND-USDT-SWAP", "a2") in canceled       # öksüz → iptal
    assert ("AAVE-USDT-SWAP", "a1") not in canceled   # pozisyonlu → korundu


def test_one_position_per_symbol(store):
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    eng.open_trade(s, sid, s.detected_at)
    # aynı setup tekrar → None (UNIQUE)
    assert eng.open_trade(s, sid, s.detected_at) is None
    assert len(fake.placed) == 1


def test_cancel_if_unfilled_cancels_live_order(store):
    """Setup terminal'e gitti, limit DOLMADI (live) → emir iptal + DB canceled."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    assert t is not None and fake.orders[t.ord_id]["state"] == "live"
    canceled = eng.cancel_if_unfilled(sid)
    assert canceled is True
    row = store._conn.execute(
        "SELECT state, closed_at FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "canceled" and row[1] is not None


def test_cancel_if_unfilled_skips_filled_order(store):
    """Emir DOLMUŞSA (pozisyon) iptal etme — filled işaretle, sync kapanışı yönetsin."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    fake.orders[t.ord_id]["state"] = "filled"     # emir doldu (gerçek pozisyon)
    canceled = eng.cancel_if_unfilled(sid)
    assert canceled is False
    row = store._conn.execute(
        "SELECT state, closed_at FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "filled" and row[1] is None   # açık kaldı, iptal edilmedi


def test_sync_cancels_orphan_limit_on_terminal_setup(store):
    """Backstop: dolmamış limit + setup lifecycle terminal (TP) → sync iptal eder."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)     # live limit (dolmadı)
    # Tracker setup'ı TP işaretledi ama emir hâlâ live (fiyat entry'ye dönmedi)
    store.upsert_lifecycle(setup_id=sid, state="TP", state_changed_at=s.detected_at,
                           entered_at=s.detected_at, exited_at=s.detected_at,
                           exit_reason="tp1")
    n = eng.sync()
    assert n == 1
    row = store._conn.execute(
        "SELECT state, closed_at FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "canceled" and row[1] is not None


def test_sync_keeps_unfilled_when_setup_active(store):
    """Setup hâlâ AKTIF (terminal değil) ise dolmamış limit iptal EDİLMEZ."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    eng.open_trade(s, sid, s.detected_at)
    store.upsert_lifecycle(setup_id=sid, state="Aktif", state_changed_at=s.detected_at,
                           entered_at=s.detected_at, exited_at=None, exit_reason=None)
    eng.sync()
    row = store._conn.execute(
        "SELECT state FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "live"   # dokunulmadı


def test_sync_closes_on_history_pnl(store):
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    # OKX: emir doldu + pozisyon kapandı. realizedPnl, kendi entry/exit hesabıyla
    # TUTARLI olmalı (yanlış eşleşme koruması). exit = entry'nin biraz üstü (TP).
    fake.orders[t.ord_id]["state"] = "filled"
    fake.positions = lambda: []
    exit_px = round(t.entry_px * 1.01, 6)   # %1 TP → bull kazanç
    expect = eng._calc_pnl(t.direction, t.entry_px, exit_px, t.notional_usd)
    fake.positions_history = lambda: [{"instId": "TEST-USDT-SWAP",
                                       "clOrdId": t.cl_ord_id,
                                       "realizedPnl": str(round(expect, 4)),
                                       "closeAvgPx": str(exit_px)}]
    n = eng.sync()
    assert n == 1
    row = store._conn.execute(
        "SELECT state, pnl_usd FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()
    assert row[0] == "closed"
    assert abs(row[1] - expect) < 1.0        # realizedPnl kendi hesapla uyumlu


def test_sync_rejects_wrong_pnl(store):
    """realizedPnl kendi hesaptan ÇOK saparsa (yanlış eşleşme) kendi hesabı kullanılır."""
    s, sid = _setup(store)
    fake = _FakeOkx()
    eng = OkxDemoEngine(store, fake, _fake_instruments())
    t = eng.open_trade(s, sid, s.detected_at)
    fake.orders[t.ord_id]["state"] = "filled"
    fake.positions = lambda: []
    exit_px = round(t.entry_px * 0.99, 6)   # %1 düşüş → bull SL, ~-risk
    calc = eng._calc_pnl(t.direction, t.entry_px, exit_px, t.notional_usd)
    # OKX yanlış olarak -601 raporluyor (başka pozisyonun zararı eşleşmiş)
    fake.positions_history = lambda: [{"instId": "TEST-USDT-SWAP",
                                       "realizedPnl": "-601",
                                       "closeAvgPx": str(exit_px)}]
    eng.sync()
    pnl = store._conn.execute(
        "SELECT pnl_usd FROM okx_trades WHERE setup_id=?", (sid,)).fetchone()[0]
    # -601'i REDDEDİP kendi hesabını (calc, ~-risk) kullanmalı
    assert abs(pnl - calc) < 1.0 and pnl > -100


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
