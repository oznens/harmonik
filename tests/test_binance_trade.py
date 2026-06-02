"""Binance testnet client testleri — imza + kimlik-yok davranışı (ağsız)."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from terminal.data.binance_trade import BinanceAuthError, BinanceTestClient, _sign
from terminal.paper.binance_engine import BinanceTestEngine


def test_sign_matches_reference_hmac():
    secret = "TESTSECRET"
    query = "symbol=BTCUSDT&side=BUY&timestamp=1700000000000&recvWindow=5000"
    got = _sign(secret, query)
    expect = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    assert got == expect
    assert len(got) == 64   # SHA256 hex


def test_sign_changes_with_query():
    assert _sign("s", "a=1") != _sign("s", "a=2")


def test_no_credentials_raises(monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_SECRET", raising=False)
    c = BinanceTestClient.__new__(BinanceTestClient)
    c.api_key = c.secret = ""
    assert c.has_credentials() is False
    with pytest.raises(BinanceAuthError):
        c._request("GET", "/fapi/v2/balance")


def test_num_no_scientific_notation():
    # düşük fiyatlı coin: 2.9e-05 → '0.000029' (Binance bilimsel notasyonu reddeder)
    assert BinanceTestEngine._num(0.000029) == "0.000029"
    assert BinanceTestEngine._num(1234.0) == "1234"
    assert BinanceTestEngine._num(0.30) == "0.3"       # gereksiz sıfır kırpılır
    for v in (1e-7, 2.9e-5, 0.000123, 70000.5):
        assert "e" not in BinanceTestEngine._num(v).lower()
