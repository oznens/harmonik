"""Binance instrument sizing testleri — qty/kaldıraç hesabı (ağsız, mock instrument)."""
from __future__ import annotations

import threading
import time

from terminal.data.binance_instruments import BinanceInstruments, Instrument


def _inst_with(inst: Instrument, max_lever: float = 50) -> BinanceInstruments:
    bi = BinanceInstruments.__new__(BinanceInstruments)
    bi._cache = {inst.symbol: inst}
    bi._loaded_at = time.monotonic() + 1e9
    bi._ttl = 1e12
    bi._default_max_lever = max_lever
    bi._lock = threading.Lock()
    return bi


def test_round_qty_px_decimal_no_tail():
    inst = Instrument("BTCUSDT", tick_sz=0.1, step_sz=0.001, min_qty=0.001,
                      min_notional=5, max_lever=50)
    assert inst.round_qty(1.23456) == 1.234       # step 0.001 aşağı
    assert inst.round_px(70000.07) == 70000.0     # tick 0.1
    # ondalık step float-kuyruk üretmemeli
    doge = Instrument("DOGEUSDT", tick_sz=1e-5, step_sz=1.0, min_qty=1, min_notional=5,
                      max_lever=50)
    assert doge.round_qty(123.9) == 123.0


def test_sizing_basic_qty():
    """qty = (risk/sl_pct)/price; notional = qty*price; risk SABİT."""
    inst = Instrument("BTCUSDT", 0.1, 0.001, 0.001, 5, 50)
    bi = _inst_with(inst)
    # entry 70000, stop 68600 (%2 SL), risk $20 → notional 1000, qty ~0.0142
    s = bi.size_for("BTCUSDT", 70000, 68600, 70000, risk_usd=20, equity=1000)
    assert s.ok
    assert abs(s.sz - 0.014) < 0.001            # qty step'e yuvarlı (0.001)
    assert abs(s.notional_usd - s.sz * 70000) < 0.01   # notional = yuvarlı qty × price
    assert 950 < s.notional_usd <= 1000         # ham 1000, aşağı yuvarlama
    assert s.leverage == 50                      # aggressive → parite max


def test_max_notional_gate_skips_tight_stop():
    """OKX dersi: dar stop → büyük notional → tavanı aşan setup ELENİR."""
    inst = Instrument("BTCUSDT", 0.1, 0.001, 0.001, 5, 50)
    bi = _inst_with(inst)
    # SL %0.3 → notional = 20/0.003 = 6667 > cap 6000 → ok=False
    s = bi.size_for("BTCUSDT", 70000, 69790, 70000, risk_usd=20, equity=1000,
                    max_notional=6000)
    assert s.ok is False and "tavan" in s.reason
    # Düzeltme: düşük risk ($5) → notional 1667 < cap → geçer
    s2 = bi.size_for("BTCUSDT", 70000, 69790, 70000, risk_usd=5, equity=1000,
                     max_notional=6000)
    assert s2.ok is True


def test_target_margin():
    inst = Instrument("BTCUSDT", 0.1, 0.001, 0.001, 5, 50)
    bi = _inst_with(inst)
    s = bi.size_for("BTCUSDT", 70000, 68600, 70000, risk_usd=20, equity=1000,
                    target_margin=30)
    assert s.ok
    assert abs(s.margin_usd - 30) < 6


def test_below_min_qty_and_notional():
    inst = Instrument("BTCUSDT", 0.1, 0.001, min_qty=1.0, min_notional=5, max_lever=50)
    bi = _inst_with(inst)
    s = bi.size_for("BTCUSDT", 70000, 68600, 70000, risk_usd=20, equity=1000)
    assert s.ok is False and "min" in s.reason
    inst2 = Instrument("BTCUSDT", 0.1, 0.001, 0.001, min_notional=100000, max_lever=50)
    bi2 = _inst_with(inst2)
    s2 = bi2.size_for("BTCUSDT", 70000, 68600, 70000, risk_usd=20, equity=1000)
    assert s2.ok is False and "notional" in s2.reason


def test_zero_sl_and_low_lever():
    inst = Instrument("BTCUSDT", 0.1, 0.001, 0.001, 5, 50)
    bi = _inst_with(inst)
    assert bi.size_for("BTCUSDT", 70000, 70000, 70000, risk_usd=20, equity=1000).ok is False
    low = Instrument("XUSDT", 0.001, 1, 1, 5, 5)   # max 5x
    bil = _inst_with(low, max_lever=5)
    s = bil.size_for("XUSDT", 1.0, 0.98, 1.0, risk_usd=20, equity=1000, min_lever=10)
    assert s.ok is False and "kaldıraç düşük" in s.reason
