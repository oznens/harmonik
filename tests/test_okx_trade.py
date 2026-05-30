"""OKX demo trade client testleri — imza + kimlik-yok davranışı (ağsız)."""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from terminal.data.okx_trade import OkxDemoClient, OkxAuthError, _sign, _iso_ts


def test_sign_matches_reference_hmac():
    # OKX imza = base64(HMAC_SHA256(secret, ts+method+path+body))
    secret = "TESTSECRET"
    ts = "2020-12-08T09:08:57.715Z"
    method, path, body = "GET", "/api/v5/account/balance", ""
    got = _sign(secret, ts, method, path, body)
    # Bağımsız referans hesabı
    msg = f"{ts}{method}{path}{body}".encode()
    expect = base64.b64encode(
        hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()
    assert got == expect
    # base64 geçerli + sabit uzunluk (SHA256 → 44 char)
    assert len(got) == 44


def test_sign_changes_with_body():
    s = "x"
    a = _sign(s, "T", "POST", "/p", "")
    b = _sign(s, "T", "POST", "/p", '{"sz":"1"}')
    assert a != b   # gövde imzayı değiştirir


def test_iso_ts_format():
    ts = _iso_ts()
    # 2020-12-08T09:08:57.715Z biçimi
    assert ts.endswith("Z") and "T" in ts
    assert len(ts) == len("2020-12-08T09:08:57.715Z")


def test_no_credentials_raises(monkeypatch):
    monkeypatch.delenv("OKX_API_KEY", raising=False)
    monkeypatch.delenv("OKX_SECRET", raising=False)
    monkeypatch.delenv("OKX_PASSPHRASE", raising=False)
    c = OkxDemoClient.__new__(OkxDemoClient)
    c.api_key = c.secret = c.passphrase = ""
    assert c.has_credentials() is False
    with pytest.raises(OkxAuthError):
        c._request("GET", "/api/v5/account/balance")


def test_demo_header_present():
    c = OkxDemoClient.__new__(OkxDemoClient)
    c.api_key, c.secret, c.passphrase, c.demo = "k", "s", "p", True
    h = c._headers("GET", "/x", "")
    assert h["x-simulated-trading"] == "1"
    assert h["OK-ACCESS-KEY"] == "k" and "OK-ACCESS-SIGN" in h
    assert "OK-ACCESS-PASSPHRASE" in h and "OK-ACCESS-TIMESTAMP" in h


def test_live_mode_no_demo_header():
    c = OkxDemoClient.__new__(OkxDemoClient)
    c.api_key, c.secret, c.passphrase, c.demo = "k", "s", "p", False
    h = c._headers("GET", "/x", "")
    assert "x-simulated-trading" not in h


def test_place_order_body_with_tpsl(monkeypatch):
    # _request'i yakala, gönderilen body'yi doğrula (ağ yok)
    c = OkxDemoClient.__new__(OkxDemoClient)
    c.api_key, c.secret, c.passphrase, c.demo = "k", "s", "p", True
    captured = {}

    def fake_request(method, path, body=None):
        captured["method"] = method
        captured["path"] = path
        captured["body"] = body
        return {"data": [{"ordId": "1", "sCode": "0"}]}

    c._request = fake_request
    r = c.place_order("BTCUSDT", "buy", "1", ord_type="limit", px="70000",
                      tp_trigger="75000", sl_trigger="68000")
    b = captured["body"]
    assert captured["path"] == "/api/v5/trade/order"
    assert b["instId"] == "BTC-USDT-SWAP" and b["side"] == "buy"
    assert b["px"] == "70000" and b["sz"] == "1"
    # TP/SL attachAlgoOrds doğru kuruldu
    algo = b["attachAlgoOrds"][0]
    assert algo["tpTriggerPx"] == "75000" and algo["tpOrdPx"] == "-1"
    assert algo["slTriggerPx"] == "68000" and algo["slOrdPx"] == "-1"
    assert r["ordId"] == "1"


def test_place_order_no_tpsl_no_algo():
    c = OkxDemoClient.__new__(OkxDemoClient)
    c.api_key, c.secret, c.passphrase, c.demo = "k", "s", "p", True
    captured = {}
    c._request = lambda m, p, body=None: (captured.update(body=body) or
                                          {"data": [{"ordId": "1"}]})
    c.place_order("BTCUSDT", "sell", "2", ord_type="market")
    assert "attachAlgoOrds" not in captured["body"]
    assert "px" not in captured["body"]   # market → fiyat yok
