"""Sonuç kartları renderer + DB sorgusu testleri (terminal.web.cards)."""
from __future__ import annotations

from pathlib import Path

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.web import cards
from tests.synthetic import gartley_bull, make_xabcd_klines


def _store_with_trade(tmp_path: Path, *, closed: bool = True) -> tuple[Store, dict]:
    store = Store(path=tmp_path / "c.db")
    prices, kinds = gartley_bull()
    kl = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=1_700_000_000_000)
    store.upsert_klines("BTCUSDT", "60m", kl)
    setups = scan_klines(kl, "BTCUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    assert setups
    s = setups[0]
    sid = store.upsert_setup(s)
    closed_at = 1_700_100_000_000 if closed else None
    store._conn.execute(
        "INSERT INTO paper_trades (setup_id,symbol,interval,pattern,direction,"
        "entry_price,stop_price,tp1_price,position_usd,leverage,risk_usd,"
        "opened_at,closed_at,exit_price,outcome,pnl_usd) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, s.symbol, s.interval, s.pattern_name, s.direction,
         s.entry, s.stop, s.tp1, 100.0, 5.0, 20.0,
         1_700_050_000_000, closed_at, s.tp1 if closed else None,
         "TP" if closed else None, 25.0 if closed else None),
    )
    return store, {"setup": s, "sid": sid}


def test_load_card_trades_joins_pivots(tmp_path: Path):
    store, info = _store_with_trade(tmp_path)
    rows = cards.load_card_trades(store._conn, limit=10)
    assert len(rows) == 1
    t = rows[0]
    assert t["symbol"] == "BTCUSDT" and t["outcome"] == "TP"
    # JOIN pivotları getirdi (mini grafik için)
    for k in ("x_price", "a_price", "b_price", "c_price", "d_price"):
        assert t[k] is not None
    store.close()


def test_card_html_has_chart_and_levels(tmp_path: Path):
    store, _ = _store_with_trade(tmp_path)
    rows = cards.load_card_trades(store._conn, limit=10)
    h = cards.card_html(rows[0])
    assert "BTCUSDT" in h
    assert "<svg" in h and "<polyline" in h        # XABCD mini grafik çizildi
    assert "D ZONE" in h and "Entry" in h and "SL" in h and "TP" in h
    assert "Sonuç" in h                            # kapanmış → sonuç tarihi
    assert 'class="tc-status g"' in h              # TP → yeşil status
    store.close()


def test_open_trade_card_shows_acik(tmp_path: Path):
    store, _ = _store_with_trade(tmp_path, closed=False)
    rows = cards.load_card_trades(store._conn, limit=10)
    h = cards.card_html(rows[0])
    assert "AÇIK" in h and "Açıldı" in h
    store.close()


def test_only_closed_filter(tmp_path: Path):
    store, _ = _store_with_trade(tmp_path, closed=False)
    assert cards.load_card_trades(store._conn, only_closed=True) == []
    assert len(cards.load_card_trades(store._conn, only_closed=False)) == 1
    store.close()


def test_cards_grid_empty():
    out = cards.cards_grid_html([], "boş")
    assert "boş" in out and "tcard" not in out


def test_pattern_color_mapping():
    assert cards.pattern_color("Gartley") == "#26a69a"
    assert cards.pattern_color("Bat") == "#ef5350"
    assert cards.pattern_color("Butterfly") == "#d4a72c"
    assert cards.pattern_color("Shark") == "#9aa0aa"
    assert cards.pattern_color("1.27 AB=CD") == "#26c6da"
    assert cards.pattern_color("???") == "#9aa0aa"   # bilinmeyen → varsayılan


def test_mini_svg_handles_missing_pivots():
    out = cards._mini_svg([None, 1, 2, 3, 4], [1, 2, 3, 4, 5], "#fff")
    assert "grafik yok" in out and "<polyline" not in out


def test_cards_page_is_standalone_html(tmp_path: Path):
    store, _ = _store_with_trade(tmp_path)
    rows = cards.load_card_trades(store._conn, limit=10)
    page = cards.cards_page(rows)
    assert page.startswith("<!doctype html>")
    assert ".tcards" in page and "tcard" in page   # CSS + kartlar gömülü
    store.close()
