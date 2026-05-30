"""OKX futures client testleri — sembol map + parse (ağsız, mock veriyle)."""
from __future__ import annotations

from terminal.data.okx_futures import OkxFuturesClient, _to_inst, _BAR_MAP


def test_symbol_mapping():
    assert _to_inst("BTCUSDT") == "BTC-USDT-SWAP"
    assert _to_inst("ETHUSDT") == "ETH-USDT-SWAP"
    assert _to_inst("BTC-USDT-SWAP") == "BTC-USDT-SWAP"   # zaten OKX → dokunma


def test_bar_map_covers_live_tfs():
    # Canlı sistemin tüm TF'leri + 2h native
    for tf, expect in [("15m", "15m"), ("30m", "30m"), ("60m", "1H"),
                       ("2h", "2H"), ("4h", "4H"), ("1d", "1D")]:
        assert _BAR_MAP[tf] == expect


def test_parse_okx_candles():
    # OKX kolon: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm], yeni→eski gelir
    c = OkxFuturesClient.__new__(OkxFuturesClient)   # __init__'siz (ağ açma)
    raw = [
        ["1700003600000", "101", "105", "100", "104", "50", "0.5", "5200", "1"],
        ["1700000000000", "100", "102", "99", "101", "40", "0.4", "4040", "1"],
    ]
    out = c._parse(raw, sec_per_bar=3600)
    assert len(out) == 2
    # eski→yeni sıralanmış olmalı
    assert out[0]["open_time"] == 1700000000000
    assert out[1]["open_time"] == 1700003600000
    b = out[1]
    assert b["open"] == 101.0 and b["high"] == 105.0
    assert b["low"] == 100.0 and b["close"] == 104.0
    assert b["volume"] == 0.5          # volCcy (coin)
    assert b["quote_volume"] == 5200.0  # USDT cirosu
    assert b["close_time"] == 1700003600000 + 3600 * 1000 - 1


def test_parse_short_row_fallback():
    # confirm/quote eksikse çökmeden parse
    c = OkxFuturesClient.__new__(OkxFuturesClient)
    raw = [["1700000000000", "100", "102", "99", "101", "40"]]
    out = c._parse(raw, 3600)
    assert len(out) == 1 and out[0]["volume"] == 40.0
    assert out[0]["quote_volume"] is None
