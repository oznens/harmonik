"""OKX V5 authenticated istemci — DEMO trading (emir + hesap).

Demo modu: her isteğe `x-simulated-trading: 1` başlığı eklenir; demo API anahtarı
kullanılır. Canlı emir VERMEZ — sahte para, gerçek borsa emir akışı.

Kimlik bilgileri ENV'den okunur (sohbete/repoya YAZILMAZ):
    OKX_API_KEY, OKX_SECRET, OKX_PASSPHRASE

İmza (OKX V5): base64( HMAC_SHA256( secret, timestamp + method + path + body ) )
  timestamp = ISO8601 UTC ms (2020-12-08T09:08:57.715Z)
  body = POST gövdesi (GET'te ""), path = query dahil request yolu.

MEXC futures sembolü (BTCUSDT) → OKX SWAP (BTC-USDT-SWAP). Paper motoruyla aynı
kavramlar: long/short, limit giriş, sz=kontrat adedi.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT
from terminal.data.okx_futures import OKX_BASE, _to_inst

log = logging.getLogger(__name__)

_MIN_REQUEST_INTERVAL = float(os.environ.get("OKX_MIN_INTERVAL", "0.12"))


class OkxAuthError(Exception):
    """OKX kimlik/emir hatası (kimlik eksik veya API reddi)."""


def _iso_ts() -> str:
    """OKX imza timestamp'i: ISO8601 UTC, milisaniye + 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _sign(secret: str, ts: str, method: str, path: str, body: str) -> str:
    """base64(HMAC_SHA256(secret, ts+method+path+body))."""
    msg = f"{ts}{method}{path}{body}".encode()
    mac = hmac.new(secret.encode(), msg, hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


class OkxDemoClient:
    """OKX demo (simulated) trading — emir + hesap. ENV'den kimlik okur."""

    _rate_lock = threading.Lock()
    _last_ts = 0.0

    def __init__(self, base_url: str = OKX_BASE, timeout: float = HTTP_TIMEOUT,
                 demo: bool = True) -> None:
        self.api_key = os.environ.get("OKX_API_KEY", "")
        self.secret = os.environ.get("OKX_SECRET", "")
        self.passphrase = os.environ.get("OKX_PASSPHRASE", "")
        self.demo = demo
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (okx-demo)"},
        )

    def has_credentials(self) -> bool:
        return bool(self.api_key and self.secret and self.passphrase)

    @classmethod
    def _throttle(cls) -> None:
        with cls._rate_lock:
            now = time.monotonic()
            wait = _MIN_REQUEST_INTERVAL - (now - cls._last_ts)
            if wait > 0:
                time.sleep(wait)
            cls._last_ts = time.monotonic()

    def _headers(self, method: str, path: str, body: str) -> dict[str, str]:
        ts = _iso_ts()
        h = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": _sign(self.secret, ts, method, path, body),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            h["x-simulated-trading"] = "1"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.has_credentials():
            raise OkxAuthError(
                "OKX kimlik eksik — OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE "
                "environment değişkenlerini ayarla (demo trading API anahtarı).")
        body_str = json.dumps(body) if body else ""
        self._throttle()
        try:
            r = self._client.request(method, path, content=body_str or None,
                                     headers=self._headers(method, path, body_str))
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise OkxAuthError(f"okx {method} {path}: {e}") from e
        if payload.get("code") not in ("0", 0):
            raise OkxAuthError(f"okx API reddi: {payload.get('code')} "
                               f"{payload.get('msg')} | {payload.get('data')}")
        return payload

    # ---- hesap ----

    def balance(self, ccy: str = "USDT") -> dict[str, Any]:
        """Demo hesap bakiyesi (varsayılan USDT). Ham OKX data[0] döner."""
        p = self._request("GET", f"/api/v5/account/balance?ccy={ccy}")
        data = p.get("data", [{}])
        return data[0] if data else {}

    def positions(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        """Açık demo pozisyonlar."""
        p = self._request("GET", f"/api/v5/account/positions?instType={inst_type}")
        return p.get("data", [])

    # ---- emir ----

    def place_order(self, symbol: str, side: str, sz: str,
                    ord_type: str = "limit", px: str | None = None,
                    td_mode: str = "cross", pos_side: str | None = None,
                    cl_ord_id: str | None = None,
                    tp_trigger: str | None = None, sl_trigger: str | None = None,
                    lever: int | None = None) -> dict[str, Any]:
        """Demo SWAP emri gönder (opsiyonel iliştirilmiş TP/SL).

        Args:
            symbol: BTCUSDT (→ BTC-USDT-SWAP).
            side: "buy" (long aç) | "sell" (short aç).
            sz: kontrat adedi (string).
            ord_type: "limit" | "market".
            px: limit fiyatı (limit'te zorunlu).
            td_mode: "cross" | "isolated".
            pos_side: "long" | "short" (hedge modunda); None=net mod.
            cl_ord_id: müşteri emir id (idempotent takip).
            tp_trigger/sl_trigger: iliştirilmiş TP/SL tetik fiyatı (parent dolunca
                aktif; market'ten kapat → ordPx=-1). OKX attachAlgoOrds.
        Returns: OKX data[0] (ordId, clOrdId, sCode, sMsg...).
        """
        body: dict[str, Any] = {
            "instId": _to_inst(symbol), "tdMode": td_mode,
            "side": side, "ordType": ord_type, "sz": sz,
        }
        if px is not None and ord_type == "limit":
            body["px"] = px
        if pos_side:
            body["posSide"] = pos_side
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        # İliştirilmiş TP/SL (parent dolunca aktif; -1 = market çıkış)
        if tp_trigger or sl_trigger:
            algo: dict[str, Any] = {}
            if tp_trigger:
                algo["tpTriggerPx"] = tp_trigger
                algo["tpOrdPx"] = "-1"
            if sl_trigger:
                algo["slTriggerPx"] = sl_trigger
                algo["slOrdPx"] = "-1"
            body["attachAlgoOrds"] = [algo]
        p = self._request("POST", "/api/v5/trade/order", body)
        data = p.get("data", [{}])
        return data[0] if data else {}

    def set_leverage(self, symbol: str, lever: int, td_mode: str = "cross") -> dict:
        """Parite için kaldıraç ayarla (emir öncesi). Hata olursa yutar (best-effort)."""
        try:
            p = self._request("POST", "/api/v5/account/set-leverage",
                              {"instId": _to_inst(symbol), "lever": str(lever),
                               "mgnMode": td_mode})
            data = p.get("data", [{}])
            return data[0] if data else {}
        except OkxAuthError as e:
            log.warning("set_leverage(%s, %sx): %s", symbol, lever, e)
            return {}

    def cancel_order(self, symbol: str, ord_id: str) -> dict[str, Any]:
        p = self._request("POST", "/api/v5/trade/cancel-order",
                          {"instId": _to_inst(symbol), "ordId": ord_id})
        data = p.get("data", [{}])
        return data[0] if data else {}

    def order_state(self, symbol: str, ord_id: str) -> dict[str, Any]:
        """Tek emrin durumu (live/filled/canceled...)."""
        p = self._request("GET",
                          f"/api/v5/trade/order?instId={_to_inst(symbol)}&ordId={ord_id}")
        data = p.get("data", [{}])
        return data[0] if data else {}

    def positions_history(self, inst_type: str = "SWAP",
                          limit: int = 100) -> list[dict[str, Any]]:
        """Kapanmış pozisyon geçmişi — realizedPnl içerir (P&L kesinleştirme)."""
        p = self._request(
            "GET", f"/api/v5/account/positions-history?instType={inst_type}&limit={limit}")
        return p.get("data", [])

    def ping_auth(self) -> bool:
        """Kimlik doğru mu — bakiye çekmeyi dener."""
        try:
            self.balance()
            return True
        except OkxAuthError:
            return False

    def close(self) -> None:
        self._client.close()
