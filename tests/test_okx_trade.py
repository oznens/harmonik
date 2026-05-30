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
