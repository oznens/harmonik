"""OKX sağlık kontrolü CLI testleri — korumasız poz / öksüz OCO tespiti (ağsız)."""
from __future__ import annotations

import terminal.cli.okx_health as health


class _FakeClient:
    def __init__(self, positions, oco, bal=None):
        self._pos = positions
        self._oco = oco
        self._bal = bal or {"details": [{"ccy": "USDT", "availBal": "1000"}]}

    def has_credentials(self):
        return True

    def positions(self, inst_type="SWAP"):
        return self._pos

    def algo_pending(self, ord_type="oco", inst_type="SWAP"):
        return self._oco

    def balance(self, ccy="USDT"):
        return self._bal

    def close(self):
        pass


def _patch(monkeypatch, client):
    monkeypatch.setattr(health, "OkxDemoClient", lambda *a, **k: client)


def test_all_protected_returns_zero(monkeypatch, capsys):
    """Tüm pozisyonlar OCO korumalı + öksüz yok → sorun yok (rc=0)."""
    cl = _FakeClient(
        positions=[{"instId": "AAVE-USDT-SWAP", "pos": "184", "avgPx": "81.54"}],
        oco=[{"instId": "AAVE-USDT-SWAP", "algoId": "a1",
              "tpTriggerPx": "82", "slTriggerPx": "80"}])
    _patch(monkeypatch, cl)
    rc = health.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "korumalı" in out and "Öksüz OCO yok" in out


def test_unprotected_position_flagged(monkeypatch, capsys):
    """OCO'su olmayan açık pozisyon → KORUMASIZ uyarısı + rc=1."""
    cl = _FakeClient(
        positions=[{"instId": "ALGO-USDT-SWAP", "pos": "-1183",
                    "avgPx": "0.1252060862214732"}],
        oco=[])
    _patch(monkeypatch, cl)
    rc = health.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "KORUMASIZ" in out and "ALGO-USDT-SWAP" in out
    assert "eski birikme" in out          # 16-hane avgPx etiketi


def test_orphan_oco_flagged(monkeypatch, capsys):
    """Pozisyonu olmayan OCO → ÖKSÜZ uyarısı + rc=1."""
    cl = _FakeClient(
        positions=[],
        oco=[{"instId": "SAND-USDT-SWAP", "algoId": "a2",
              "tpTriggerPx": "0.07", "slTriggerPx": "0.06"}])
    _patch(monkeypatch, cl)
    rc = health.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ÖKSÜZ OCO" in out and "SAND-USDT-SWAP" in out


def test_quiet_suppresses_when_healthy(monkeypatch, capsys):
    """--quiet: sorun yoksa çıktı verme (rc=0, boş)."""
    cl = _FakeClient(
        positions=[{"instId": "AAVE-USDT-SWAP", "pos": "184", "avgPx": "81.54"}],
        oco=[{"instId": "AAVE-USDT-SWAP", "algoId": "a1"}])
    _patch(monkeypatch, cl)
    rc = health.main(["--quiet"])
    out = capsys.readouterr().out
    assert rc == 0 and out == ""
