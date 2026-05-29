"""Canlı grafik veri katmanı (chart_data) testleri.

Özellikle son eklenen FORMASYON SEÇİCİ (dropdown) mantığını doğrular:
  - build_payload tam, JSON-serileştirilebilir bir yük üretir (mum + katmanlar)
  - list_open_setups SADECE açık (Aktif/Aday) setup'ları döner
  - setup_id verilince o setup çizilir (selected = id)
  - geçersiz setup_id otomatik seçime düşer (selected = "auto")
  - kapalı bir setup açıkça seçilirse listeye eklenip çizilir
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.lifecycle.states import AKTIF, TP
from terminal.lifecycle.tracker import LifecycleTracker
from terminal.ui import chart_data
from tests.synthetic import bat_bull, gartley_bull, make_xabcd_klines

SYMBOL = "TESTUSDT"
INTERVAL = "60m"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


def _seed(store: Store, fn, base_time: int):
    """Sentetik fiyat fonksiyonundan bir setup üret, klines + setup'ı DB'ye yaz."""
    prices, kinds = fn()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=base_time)
    store.upsert_klines(SYMBOL, INTERVAL, klines)
    setups = scan_klines(klines, SYMBOL, INTERVAL, zigzag_threshold=0.01, min_rr=0.0)
    assert setups, "sentetik veriden setup üretilemedi"
    s = setups[0]
    sid = store.upsert_setup(s)
    return s, sid, klines


def test_build_payload_well_formed(store: Store):
    s, sid, klines = _seed(store, gartley_bull, base_time=1_700_000_000_000)
    LifecycleTracker(SYMBOL, INTERVAL, store).register_new(s, sid, aggressive_entry=True)

    payload = chart_data.build_payload(store, SYMBOL, INTERVAL)

    # JSON'a serileştirilebilmeli (bridge JSON ile gönderiyor)
    json.dumps(payload)

    assert payload["type"] == "full"
    assert payload["symbol"] == SYMBOL
    assert payload["interval"] == INTERVAL
    assert len(payload["candles"]) == len(klines)
    assert len(payload["volume"]) == len(klines)
    # Mum alanları doğru anahtarlarda + zaman saniye (UTC) cinsinden
    c0 = payload["candles"][0]
    assert set(c0) == {"time", "open", "high", "low", "close"}
    assert c0["time"] == klines[0]["open_time"] // 1000
    # Katmanlar
    assert payload["pivots"]["markers"], "zigzag pivot işaretleri olmalı"
    assert payload["vector"]["line"], "vector (zigzag) çizgisi olmalı"
    assert payload["harmonic"]["present"] is True
    assert payload["harmonic"]["id"] == sid
    # XABCD harf işaretleri + Entry/SL/TP seviyeleri
    letters = {m["text"] for m in payload["harmonic"]["markers"]}
    assert {"X", "A", "B", "C", "D"} <= letters
    titles = {lv["title"] for lv in payload["harmonic"]["levels"]}
    # Tek hedef ("Hedef" = tp1); tp2 görselde gösterilmez (rr1 tek 1:1 hedef).
    assert {"Entry", "SL", "Hedef"} <= titles
    assert "TP2" not in titles
    # Seçici listesi + varsayılan "auto"
    assert payload["selected"] == "auto"
    assert any(opt["id"] == sid for opt in payload["setups"])


def test_harmonic_layer_abcd_x_equals_a_deduped(store: Store):
    """AB=CD ailesinde X==A (aynı bar): harmonic çizgi zaman bazında tekillenmeli.
    Yoksa lightweight-charts setData yinelenen zamanı reddedip canlı grafiği
    sessizce patlatır (AB=CD canlıda aktif edilince ortaya çıkar)."""
    from terminal.detection.models import Pivot, Setup

    step, base = 3_600_000, 1_700_000_000_000
    klines = [{"open_time": base + i * step, "close_time": base + i * step + step - 1,
               "open": 100.0 + i, "high": 100.5 + i, "low": 99.5 + i, "close": 100.0 + i,
               "volume": 100.0, "quote_volume": 1e4} for i in range(40)]
    store.upsert_klines(SYMBOL, INTERVAL, klines)

    a = Pivot(index=2, time=klines[2]["open_time"], price=101.0, kind="low")
    setup = Setup(
        symbol=SYMBOL, interval=INTERVAL, pattern_name="1.27 AB=CD", direction="bull",
        pivots={"X": a, "A": a,   # AB=CD: X yuvası A'nın kopyası → aynı zaman
                "B": Pivot(5, klines[5]["open_time"], 104.0, "high"),
                "C": Pivot(8, klines[8]["open_time"], 102.0, "low"),
                "D": Pivot(12, klines[12]["open_time"], 100.0, "high")},
        b_ratio=0.0, c_ratio=0.5, d_ratio=0.786, bc_proj=1.27, cd_ab_ratio=1.0,
        ab_cd_equivalent=True, prz_low=99.5, prz_high=100.5,
        prz_components=[("x", 100.0)], entry=100.0, stop=98.0, tp1=104.0, tp2=106.0,
        detected_at=klines[12]["open_time"], pattern_family="abcd")
    sid = store.upsert_setup(setup)

    h = chart_data._harmonic_layer(store, SYMBOL, INTERVAL, setup_id=sid)
    assert h["present"] is True
    times = [p["time"] for p in h["line"]]
    assert times == sorted(set(times)), f"yinelenen/sırasız pivot zamanı: {times}"
    assert len(h["line"]) == 4   # X ve A tek noktaya indi → A,B,C,D
    json.dumps(h)                # JSON-serileştirilebilir kalmalı


def test_list_open_setups_excludes_closed(store: Store):
    # Açık (Aktif) setup
    s_open, sid_open, _ = _seed(store, gartley_bull, base_time=1_700_000_000_000)
    LifecycleTracker(SYMBOL, INTERVAL, store).register_new(
        s_open, sid_open, aggressive_entry=True)
    # Kapalı (TP) setup
    s_closed, sid_closed, _ = _seed(store, bat_bull, base_time=1_700_100_000_000)
    store.upsert_lifecycle(sid_closed, TP, state_changed_at=1_700_200_000_000,
                           exited_at=1_700_200_000_000, exit_reason="tp1")

    opens = chart_data.list_open_setups(store, SYMBOL, INTERVAL)
    open_ids = {o["id"] for o in opens}
    assert sid_open in open_ids
    assert sid_closed not in open_ids
    # Etiket biçimi: "YÖN Pattern ... · State"
    label = next(o["label"] for o in opens if o["id"] == sid_open)
    assert label.startswith("BULL ")
    assert AKTIF in label


def test_explicit_setup_id_is_selected(store: Store):
    s_a, sid_a, _ = _seed(store, gartley_bull, base_time=1_700_000_000_000)
    s_b, sid_b, _ = _seed(store, bat_bull, base_time=1_700_100_000_000)
    tr = LifecycleTracker(SYMBOL, INTERVAL, store)
    tr.register_new(s_a, sid_a, aggressive_entry=True)
    tr.register_new(s_b, sid_b, aggressive_entry=True)

    # Otomatik: en yeni D zamanlı (sid_b) çizilir
    auto = chart_data.build_payload(store, SYMBOL, INTERVAL)
    assert auto["harmonic"]["id"] == sid_b
    assert auto["selected"] == "auto"

    # Açıkça eski setup'ı (sid_a) seç → o çizilmeli
    chosen = chart_data.build_payload(store, SYMBOL, INTERVAL, setup_id=sid_a)
    assert chosen["harmonic"]["id"] == sid_a
    assert chosen["selected"] == str(sid_a)


def test_invalid_setup_id_falls_back_to_auto(store: Store):
    s, sid, _ = _seed(store, gartley_bull, base_time=1_700_000_000_000)
    LifecycleTracker(SYMBOL, INTERVAL, store).register_new(s, sid, aggressive_entry=True)

    payload = chart_data.build_payload(store, SYMBOL, INTERVAL, setup_id=999_999)
    # Var olmayan id → mevcut setup'a düşer, "auto" gösterilir (yanlış seçim göstermez)
    assert payload["harmonic"]["present"] is True
    assert payload["harmonic"]["id"] == sid
    assert payload["selected"] == "auto"


def test_closed_setup_id_inserted_into_dropdown(store: Store):
    # Açık setup (dropdown'da normalde görünen)
    s_open, sid_open, _ = _seed(store, gartley_bull, base_time=1_700_000_000_000)
    LifecycleTracker(SYMBOL, INTERVAL, store).register_new(
        s_open, sid_open, aggressive_entry=True)
    # Kapalı setup — list_open_setups DÖNMEZ
    s_closed, sid_closed, _ = _seed(store, bat_bull, base_time=1_700_100_000_000)
    store.upsert_lifecycle(sid_closed, TP, state_changed_at=1_700_200_000_000,
                           exited_at=1_700_200_000_000, exit_reason="tp1")

    payload = chart_data.build_payload(store, SYMBOL, INTERVAL, setup_id=sid_closed)
    # Kapalı setup açıkça seçildi → çizilir, seçili gösterilir
    assert payload["harmonic"]["id"] == sid_closed
    assert payload["selected"] == str(sid_closed)
    # ve listenin başına eklenmiş olmalı (kullanıcı seçimini koruyabilsin)
    assert payload["setups"][0]["id"] == sid_closed
    # açık setup da hâlâ listede
    assert any(o["id"] == sid_open for o in payload["setups"])
