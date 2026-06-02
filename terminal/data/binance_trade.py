"""Binance USDT-M Futures TESTNET authenticated istemci (emir + hesap).

OkxDemoClient karşılığı. Testnet = sahte para, gerçek borsa emir akışı.
Kimlik ENV'den (sohbete/repoya YAZILMAZ):  BINANCE_API_KEY, BINANCE_SECRET
(testnet.binancefuture.com'dan üretilir; passphrase YOK).

İmza (Binance): signature = hex( HMAC_SHA256(secret, query_string) ).
  query_string = tüm parametreler + timestamp + recvWindow (urlencode sırasıyla).
  Header: X-MBX-APIKEY. POST'ta da parametreler query string'de gider.

TP/SL: bu testnet STOP_MARKET/TAKE_PROFIT_MARKET'i /fapi/v1/order'da REDDEDİYOR
(-4120). Bu yüzden çıkış ENGINE-YÖNETİMLİ: motor markPrice'a bakıp seviyeye değince
MARKET reduceOnly ile kapatır (bkz. binance_engine.sync). place_order yine
STOP_MARKET/closePosition destekler (mainnet / ileride lazım olursa).

Sembol: BTCUSDT (dönüşüm yok). Net (one-way) mod varsayılır (positionSide=BOTH).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from terminal.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

BINANCE_TESTNET = "https://testnet.binancefuture.com"
_MIN_REQUEST_INTERVAL = float(os.environ.get("BINANCE_MIN_INTERVAL", "0.06"))
_RECV_WINDOW = 5000


class BinanceAuthError(Exception):
    """Binance kimlik/emir hatası (kimlik eksik veya API reddi)."""


def _sign(secret: str, query: str) -> str:
    """Binance imza: hex(HMAC_SHA256(secret, query_string))."""
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BinanceTestClient:
    """Binance futures TESTNET trading — emir + hesap. ENV'den kimlik okur."""

    _rate_lock = threading.Lock()
    _last_ts = 0.0

    def __init__(self, base_url: str = BINANCE_TESTNET,
                 timeout: float = HTTP_TIMEOUT) -> None:
        self.api_key = os.environ.get("BINANCE_API_KEY", "")
        self.secret = os.environ.get("BINANCE_SECRET", "")
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (binance-test)",
                     "X-MBX-APIKEY": self.api_key},
        )

    def has_credentials(self) -> bool:
        return bool(self.api_key and self.secret)

    @classmethod
    def _throttle(cls) -> None:
        with cls._rate_lock:
            now = time.monotonic()
            wait = _MIN_REQUEST_INTERVAL - (now - cls._last_ts)
            if wait > 0:
                time.sleep(wait)
            cls._last_ts = time.monotonic()

    def _request(self, method: str, path: str,
                 params: dict[str, Any] | None = None, signed: bool = True) -> Any:
        if signed and not self.has_credentials():
            raise BinanceAuthError(
                "Binance kimlik eksik — BINANCE_API_KEY / BINANCE_SECRET ayarla "
                "(testnet.binancefuture.com trading API anahtarı).")
        p = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            p["timestamp"] = int(time.time() * 1000)
            p["recvWindow"] = _RECV_WINDOW
            query = urlencode(p)
            url = f"{path}?{query}&signature={_sign(self.secret, query)}"
        else:
            url = f"{path}?{urlencode(p)}" if p else path
        self._throttle()
        try:
            r = self._client.request(method, url)
        except httpx.HTTPError as e:
            raise BinanceAuthError(f"binance {method} {path}: {e}") from e
        try:
            payload = r.json()
        except ValueError:
            raise BinanceAuthError(f"binance {method} {path}: HTTP {r.status_code} {r.text[:120]}")
        if r.status_code != 200 or (isinstance(payload, dict) and payload.get("code", 0)
                                    not in (0, 200) and "code" in payload and "msg" in payload):
            raise BinanceAuthError(f"binance API reddi: {payload.get('code')} "
                                   f"{payload.get('msg')} ({method} {path})")
        return payload

    # ---- hesap ----

    def balance(self) -> dict[str, Any]:
        """USDT bakiye kalemi (/fapi/v2/balance). {balance, availableBalance,...}."""
        data = self._request("GET", "/fapi/v2/balance")
        for d in data:
            if d.get("asset") == "USDT":
                return d
        return {}

    def equity(self) -> float | None:
        """USDT cüzdan bakiyesi (wallet balance)."""
        try:
            return float(self.balance().get("balance") or 0) or None
        except (ValueError, TypeError):
            return None

    def free_usdt(self) -> float | None:
        """Boş (kullanılabilir) USDT margin."""
        try:
            av = self.balance().get("availableBalance")
            return float(av) if av is not None else None
        except (ValueError, TypeError):
            return None

    def account(self) -> dict[str, Any]:
        """Futures hesap özeti (/fapi/v2/account): totalWalletBalance,
        totalMarginBalance, totalUnrealizedProfit, availableBalance."""
        return self._request("GET", "/fapi/v2/account")

    def positions(self) -> list[dict[str, Any]]:
        """Açık pozisyonlar (/fapi/v2/positionRisk) — positionAmt != 0 olanlar."""
        data = self._request("GET", "/fapi/v2/positionRisk")
        out = []
        for p in data:
            try:
                if float(p.get("positionAmt") or 0) != 0.0:
                    out.append(p)
            except (ValueError, TypeError):
                continue
        return out

    def position_for(self, symbol: str) -> dict[str, Any] | None:
        for p in self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}):
            try:
                if float(p.get("positionAmt") or 0) != 0.0:
                    return p
            except (ValueError, TypeError):
                pass
        return None

    # ---- ayar ----

    def set_one_way_mode(self) -> None:
        """Hesabı net (one-way) moda al — positionSide=BOTH ile emir için. Best-effort
        (zaten one-way ise -4059 döner, yutulur)."""
        try:
            self._request("POST", "/fapi/v1/positionSide/dual",
                          {"dualSidePosition": "false"})
        except BinanceAuthError as e:
            if "-4059" not in str(e):   # 'No need to change position side'
                log.warning("set_one_way_mode: %s", e)

    def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        """Parite kaldıracını ayarla (best-effort; izin verilenden büyükse Binance clamp)."""
        try:
            return self._request("POST", "/fapi/v1/leverage",
                                 {"symbol": symbol, "leverage": int(leverage)})
        except BinanceAuthError as e:
            log.warning("set_leverage(%s, %sx): %s", symbol, leverage, e)
            return {}

    def set_margin_type(self, symbol: str, margin_type: str = "CROSSED") -> None:
        """Cross/isolated. Zaten o moddaysa -4046 döner (yutulur)."""
        try:
            self._request("POST", "/fapi/v1/marginType",
                          {"symbol": symbol, "marginType": margin_type})
        except BinanceAuthError as e:
            if "-4046" not in str(e):   # 'No need to change margin type'
                log.warning("set_margin_type(%s): %s", symbol, e)

    # ---- emir ----

    def place_order(self, symbol: str, side: str, qty: float | str | None = None,
                    ord_type: str = "LIMIT", price: str | None = None,
                    stop_price: str | None = None, close_position: bool = False,
                    reduce_only: bool = False, time_in_force: str = "GTC",
                    client_id: str | None = None,
                    working_type: str = "MARK_PRICE") -> dict[str, Any]:
        """Tek emir gönder. side: BUY/SELL. ord_type: LIMIT/MARKET/STOP_MARKET/
        TAKE_PROFIT_MARKET. close_position=True → closePosition emri (qty gerekmez)."""
        body: dict[str, Any] = {"symbol": symbol, "side": side, "type": ord_type}
        if close_position:
            body["closePosition"] = "true"
            body["stopPrice"] = stop_price
            body["workingType"] = working_type
        else:
            if qty is not None:
                body["quantity"] = qty
            if reduce_only:
                body["reduceOnly"] = "true"
            if ord_type == "LIMIT":
                body["price"] = price
                body["timeInForce"] = time_in_force
            if stop_price is not None:
                body["stopPrice"] = stop_price
                body["workingType"] = working_type
        if client_id:
            body["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", body)

    def order_state(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        """Emir durumu (/fapi/v1/order). status: NEW/FILLED/CANCELED/EXPIRED..."""
        return self._request("GET", "/fapi/v1/order",
                             {"symbol": symbol, "orderId": order_id})

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self._request("GET", "/fapi/v1/openOrders",
                            {"symbol": symbol} if symbol else None)

    def cancel_order(self, symbol: str, order_id: str | int) -> dict[str, Any]:
        return self._request("DELETE", "/fapi/v1/order",
                            {"symbol": symbol, "orderId": order_id})

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        """Paritedeki tüm açık emirleri iptal (öksüz TP/SL temizliği)."""
        try:
            return self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})
        except BinanceAuthError as e:
            log.warning("cancel_all(%s): %s", symbol, e)
            return {}

    def realized_pnl(self, symbol: str, since_ms: int | None = None) -> float:
        """Paritenin gerçekleşmiş P&L toplamı (/fapi/v1/income REALIZED_PNL)."""
        params: dict[str, Any] = {"symbol": symbol, "incomeType": "REALIZED_PNL",
                                  "limit": 100}
        if since_ms:
            params["startTime"] = since_ms
        try:
            data = self._request("GET", "/fapi/v1/income", params)
        except BinanceAuthError:
            return 0.0
        return sum(float(x.get("income") or 0) for x in data)

    def ping_auth(self) -> bool:
        """Kimlik doğru mu — bakiye çekmeyi dener."""
        try:
            self.balance()
            return True
        except BinanceAuthError:
            return False

    def close(self) -> None:
        self._client.close()
