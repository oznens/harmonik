"""gen_top_combos saf mantık testleri (ağsız)."""
from __future__ import annotations

import gen_top_combos as g


def test_pick_intersect_preserves_marketcap_order():
    # CoinGecko sırası (piyasa değeri azalan): BTC, ETH, USDT, BNB, SOL, WBTC, XRP
    ranked = [("BTC", 9), ("ETH", 8), ("USDT", 7), ("BNB", 6),
              ("SOL", 5), ("WBTC", 4), ("XRP", 3)]
    futures = {"BTC", "ETH", "BNB", "SOL", "XRP", "USDT", "WBTC"}
    picked = g.pick_intersect(ranked, futures, n=4)
    # USDT (stable) ve WBTC (wrapped) dışlanır; sıra korunur
    assert [s for s, _ in picked] == ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]


def test_pick_intersect_skips_not_on_futures():
    ranked = [("BTC", 9), ("ETH", 8), ("FOO", 7), ("XRP", 3)]
    futures = {"BTC", "ETH", "XRP"}  # FOO futures'ta yok
    picked = g.pick_intersect(ranked, futures, n=10)
    assert [s for s, _ in picked] == ["BTCUSDT", "ETHUSDT", "XRPUSDT"]


def test_pick_intersect_dedup_and_cap():
    ranked = [("BTC", 9), ("BTC", 9), ("ETH", 8)]  # tekrar eden sembol
    futures = {"BTC", "ETH"}
    picked = g.pick_intersect(ranked, futures, n=10)
    assert [s for s, _ in picked] == ["BTCUSDT", "ETHUSDT"]


def test_volume_parse_fallback():
    assert g._volume({"amount24": "123.5"}) == 123.5
    assert g._volume({"volume24": 99}) == 99.0
    assert g._volume({}) == 0.0


def test_render_groups_by_tf():
    out = g.render([("BTCUSDT", 1e12), ("ETHUSDT", 4e11)], ["4h", "1d"], "marketcap")
    assert "BTCUSDT 4h" in out and "BTCUSDT 1d" in out
    assert "ETHUSDT 4h" in out and "ETHUSDT 1d" in out
    assert "2 parite × 2 TF = 4 kombinasyon" in out
    assert "piyasa değeri" in out
