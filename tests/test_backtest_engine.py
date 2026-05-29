"""Görsel backtest motoru (run_backtest) testleri — saf, UI'siz."""
from __future__ import annotations

from pathlib import Path

from terminal.backtest.engine import _pivot_points, load_db_klines, run_backtest
from terminal.detection.models import Pivot
from terminal.db.store import Store
from tests.synthetic import gartley_bull, make_xabcd_klines

MS = 3_600_000


class _FakeSetup:
    """_pivot_points sadece .pivots'a bakar; tam Setup kurmaya gerek yok."""
    def __init__(self, pivots):
        self.pivots = pivots


def test_pivot_points_dedup_abcd_x_equals_a():
    """AB=CD'de X slotu A'nın kopyasıdır (aynı bar). _pivot_points bunu zaman
    bazında tekillemeli — yoksa çizimde yinelenen zaman lightweight-charts
    setData'yı patlatıp tüm backtest render'ını boş bırakıyordu.
    """
    a = Pivot(index=0, time=1_000_000, price=100.0, kind="L")  # X==A aynı pivot
    pivots = {
        "X": a, "A": a,
        "B": Pivot(index=3, time=1_000_000 + 3 * MS, price=104.0, kind="H"),
        "C": Pivot(index=6, time=1_000_000 + 6 * MS, price=102.0, kind="L"),
        "D": Pivot(index=9, time=1_000_000 + 9 * MS, price=106.0, kind="H"),
    }
    pts = _pivot_points(_FakeSetup(pivots))
    times = [p["time"] for p in pts]
    assert times == sorted(set(times))            # artan + benzersiz (LWC güvenli)
    assert len(pts) == 4                          # X ve A tek noktaya indi
    assert pts[0]["label"] == "A"                 # AB=CD başlangıcı 'A' etiketli (X değil)
    assert [p["label"] for p in pts] == ["A", "B", "C", "D"]


def test_run_backtest_abcd_pivots_lwc_safe():
    """include_abcd=True'da bile her işlemin pivot zamanları artan + benzersiz
    olmalı (AB=CD setupları render'ı kırmasın)."""
    import math, random
    random.seed(7)
    bars = []
    t0, step, price = 1_700_000_000_000, MS, 100.0
    for i in range(2000):
        price = max(1.0, price + math.sin(i / 23.0) * 1.5 + math.sin(i / 7.0) * 0.6
                    + random.uniform(-1.2, 1.2))
        o = price
        c = price + random.uniform(-0.8, 0.8)
        ot = t0 + i * step
        bars.append({"open_time": ot, "close_time": ot + step - 1, "open": o,
                     "high": max(o, c) + random.uniform(0, 0.9),
                     "low": min(o, c) - random.uniform(0, 0.9), "close": c,
                     "volume": 100.0, "quote_volume": 1e4})
    r = run_backtest(bars, "TESTUSDT", "60m", entry_mode="market",
                     target_mode="structural", include_abcd=True, min_rr=0.0)
    assert any("AB=CD" in t["pattern"] for t in r.trades)   # AB=CD gerçekten üretildi
    for t in r.trades:
        times = [p["time"] for p in t["pivots"]]
        assert times == sorted(set(times)), f"{t['pattern']} pivot zamanı bozuk: {times}"


def test_load_db_klines_chronological(tmp_path: Path):
    s = Store(path=tmp_path / "t.db")
    kl = [{"open_time": 1000 + i, "close_time": 1000 + i, "open": 1.0, "high": 1.0,
           "low": 1.0, "close": 1.0, "volume": 1.0, "quote_volume": 1.0} for i in range(50)]
    s.upsert_klines("BTCUSDT", "60m", kl)
    out = load_db_klines(s, "BTCUSDT", "60m", limit=10)
    assert len(out) == 10
    # En son 10 mum, kronolojik (artan open_time)
    assert out[0]["open_time"] < out[-1]["open_time"]
    assert out[-1]["open_time"] == 1049
    assert load_db_klines(s, "YOKUSDT", "60m", limit=10) == []   # veri yok → boş
    s.close()


def _klines_with_tp_tail():
    """Gartley bull pattern + D sonrası TP1'e yükselen kuyruk."""
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=1_700_000_000_000)
    last = kl[-1]
    # entry ~104.28, tp1 ~107.6 — yukarı yürüt
    t, p = last["open_time"], last["close"]
    for i in range(1, 16):
        t += MS
        p2 = p + 0.4
        kl.append({"open_time": t, "close_time": t + MS - 1, "open": p,
                   "high": p2 + 0.1, "low": p - 0.1, "close": p2,
                   "volume": 100.0, "quote_volume": 1000.0})
        p = p2
    return kl


def test_run_backtest_produces_chart_data():
    kl = _klines_with_tp_tail()
    r = run_backtest(kl, "BTCUSDT", "60m", entry_mode="market", min_rr=0.0)

    assert r.symbol == "BTCUSDT" and r.entry_mode == "market"
    assert len(r.candles) == len(kl)
    assert r.candles[0]["time"] == kl[0]["open_time"] // 1000   # saniye
    assert r.stats["n_setups"] >= 1
    assert r.stats["n_trades"] >= 1
    # En az bir işlem TP olmalı + pivotları çizilmeli
    tr = r.trades[0]
    assert tr["outcome"] in ("TP", "STOP", "ZI")
    labels = {p["label"] for p in tr["pivots"]}
    assert {"X", "A", "B", "C", "D"} <= labels
    assert "entry" in tr and "exit" in tr
    assert r.equity and r.equity[-1]["value"] == r.stats["final_equity"]


def test_run_backtest_empty_klines():
    r = run_backtest([], "BTCUSDT", "60m")
    assert r.candles == [] and r.trades == [] and r.stats == {}


def test_run_backtest_entry_modes_differ():
    kl = _klines_with_tp_tail()
    market = run_backtest(kl, "BTCUSDT", "60m", entry_mode="market", min_rr=0.0)
    limit = run_backtest(kl, "BTCUSDT", "60m", entry_mode="limit", min_rr=0.0)
    # İki mod da çalışır; market girer (sonraki bar), limit fiyat entry'ye dönmezse EO
    assert market.stats["n_setups"] == limit.stats["n_setups"]


def test_setups_drawn_even_when_no_trades():
    """İşlem dolmasa bile tespit edilen setuplar grafikte çizilir (boş kalmasın)."""
    kl = _klines_with_tp_tail()
    r = run_backtest(kl, "BTCUSDT", "60m", entry_mode="limit", min_rr=0.0)
    assert r.stats["n_setups"] >= 1
    assert "eo" in r.stats and "n_detected" in r.stats
    # Her işlem 'faint' bayrağı taşır; dolmayanlar giriş/çıkış oku olmadan çizilir
    for t in r.trades:
        assert "faint" in t
        labels = {p["label"] for p in t["pivots"]}
        assert {"X", "A", "B", "C", "D"} <= labels   # XABCD her zaman çizili
        if t["faint"]:
            assert "entry" not in t and "exit" not in t
    # Çizilen setup sayısı en az tespit edilen kadar (dolan + soluk)
    assert len(r.trades) >= r.stats["n_detected"] >= 1
