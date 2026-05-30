"""OKX instrument sizing testleri — kontrat/kaldıraç hesabı (ağsız, mock instrument)."""
from __future__ import annotations

from terminal.data.okx_instruments import Instrument, OkxInstruments, Sizing


def _inst_with(symbol_inst: Instrument) -> OkxInstruments:
    """Ağ açmadan, cache'i elle doldurulmuş OkxInstruments."""
    oi = OkxInstruments.__new__(OkxInstruments)
    import threading, time
    oi._cache = {symbol_inst.inst_id: symbol_inst}
    oi._loaded_at = time.monotonic() + 1e9   # TTL hiç dolmasın
    oi._ttl = 1e12
    oi._lock = threading.Lock()
    return oi


def test_round_sz_and_px():
    inst = Instrument("BTC-USDT-SWAP", ct_val=0.01, max_lever=100,
                      min_sz=0.01, lot_sz=0.01, tick_sz=0.1)
    assert inst.round_sz(1.237) == 1.23      # lot 0.01 → aşağı
    assert inst.round_px(74000.07) == 74000.1


def test_sizing_basic_btc_aggressive():
    """Varsayılan (aggressive): max kaldıraç → margin minimum (az parayla çok poz)."""
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1)
    oi = _inst_with(inst)
    # entry 74000, stop 72000 (~%2.7 SL), $20 risk → notional ~740
    s = oi.size_for("BTCUSDT", 74000, 72000, 74000, risk_usd=20, equity=1000)
    assert s.ok
    assert abs(s.notional_usd - 740.74) < 1.0   # risk SABİT (20/(2000/74000))
    assert s.leverage == 100                      # paritenin MAX'ı → margin min
    assert abs(s.margin_usd - 7.4) < 0.1          # 740/100 = ~7.4 (az teminat)
    assert abs(s.sz - 1.0) < 0.01                 # sz risk'e göre, kaldıraçtan bağımsız


def test_target_margin():
    """Hedef margin: kaldıraç notional'a göre seçilir, her işlem ~hedef teminat."""
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1)
    oi = _inst_with(inst)
    # SL %2.7 → notional 740, hedef margin 30 → lever=740/30≈25, margin≈30
    s = oi.size_for("BTCUSDT", 74000, 72000, 74000, risk_usd=20, equity=1000,
                    target_margin=30)
    assert s.ok
    assert s.leverage == 25                  # round(740/30)
    assert abs(s.margin_usd - 30) < 5        # ~hedef margin
    assert abs(s.notional_usd - 740.74) < 1  # notional/risk değişmedi


def test_target_margin_capped_at_max_lever():
    """Çok dar stop → hedef margin için gereken kaldıraç parite max'ını aşar → max."""
    inst = Instrument("SOL-USDT-SWAP", 1.0, 50, 0.01, 0.01, 0.01)
    oi = _inst_with(inst)
    # SL %0.4 → notional 5000, hedef 30 → lever 166 gerekir ama max 50 → margin 100
    s = oi.size_for("SOLUSDT", 180, 179.28, 180, risk_usd=20, equity=1000,
                    target_margin=30)
    assert s.leverage == 50                  # paritenin max'ı (166 değil)


def test_sizing_conservative_mode():
    """aggressive_leverage=False: eski davranış (margin yüksek, az poz)."""
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1)
    oi = _inst_with(inst)
    s = oi.size_for("BTCUSDT", 74000, 72000, 74000, risk_usd=20, equity=1000,
                    aggressive_leverage=False)
    assert s.leverage == 1 and abs(s.margin_usd - 740.0) < 1.0


def test_sizing_caps_at_max_lever():
    # max 50x parite, çok dar stop → kaldıraç 50'de kapanmalı
    inst = Instrument("SOL-USDT-SWAP", 1.0, 50, 0.01, 0.01, 0.01)
    oi = _inst_with(inst)
    # entry 180, stop 179.9 (%0.055 SL) → notional ~36000, equity 100 → ham lever 360
    s = oi.size_for("SOLUSDT", 180, 179.9, 180, risk_usd=20, equity=100)
    assert s.leverage == 50      # paritenin max'ı ile sınırlı (360 değil)


def test_sizing_user_lever_cap():
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1)
    oi = _inst_with(inst)
    s = oi.size_for("BTCUSDT", 74000, 73900, 74000, risk_usd=20, equity=100,
                    max_user_lever=10)
    assert s.leverage <= 10      # kullanıcı tavanı (parite 100 izin verse de)


def test_sizing_below_min_sz():
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, min_sz=1.0, lot_sz=0.01, tick_sz=0.1)
    oi = _inst_with(inst)
    # çok küçük risk → sz < min_sz=1.0
    s = oi.size_for("BTCUSDT", 74000, 72000, 74000, risk_usd=0.5, equity=1000)
    assert s.ok is False and "min" in s.reason


def test_sizing_zero_sl():
    inst = Instrument("BTC-USDT-SWAP", 0.01, 100, 0.01, 0.01, 0.1)
    oi = _inst_with(inst)
    s = oi.size_for("BTCUSDT", 74000, 74000, 74000, risk_usd=20, equity=1000)
    assert s.ok is False
