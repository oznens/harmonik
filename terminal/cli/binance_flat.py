"""Binance testnet hesabını TAM düzleştir + (opsiyonel) dashboard verisini sıfırla.

okx_flat karşılığı (tek seferlik reset):
  1) Tüm açık pozisyonları market reduceOnly ile kapat.
  2) Tüm açık emirleri iptal et (öksüz TP/SL dahil).
  3) --wipe-db: binance_trades tablosunu temizle (paylaşılan setups'a dokunmaz).

ÖNCE servisi durdur: sudo systemctl stop harmonik-binance
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from decimal import Decimal

from terminal.config import DB_PATH
from terminal.data.binance_trade import BinanceAuthError, BinanceTestClient


def _num(x: float) -> str:
    d = Decimal(repr(float(x))).normalize()
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _flatten(client: BinanceTestClient) -> None:
    pos = client.positions()
    print(f"Açık pozisyon: {len(pos)}")
    syms = set()
    for p in pos:
        sym = p.get("symbol", "")
        syms.add(sym)
        try:
            amt = float(p.get("positionAmt") or 0)
        except (ValueError, TypeError):
            amt = 0.0
        if amt == 0:
            continue
        side = "SELL" if amt > 0 else "BUY"
        try:
            client.place_order(sym, side, qty=_num(abs(amt)), ord_type="MARKET",
                               reduce_only=True)
            print(f"  kapatıldı: {sym} ({amt})")
        except BinanceAuthError as e:
            print(f"  ATLA kapat {sym}: {e}")
    # Açık emirleri topla (pozisyonsuz öksüz TP/SL dahil)
    try:
        for o in client.open_orders():
            syms.add(o.get("symbol", ""))
    except BinanceAuthError:
        pass
    for sym in sorted(s for s in syms if s):
        try:
            client.cancel_all(sym)
            print(f"  emirler iptal: {sym}")
        except BinanceAuthError as e:
            print(f"  ATLA iptal {sym}: {e}")


def _wipe_db() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        try:
            n = conn.execute("SELECT COUNT(*) FROM binance_trades").fetchone()[0]
        except sqlite3.OperationalError:
            print("binance_trades tablosu yok — DB temizliği atlandı.")
            return
        conn.execute("DELETE FROM binance_trades")
        conn.commit()
        print(f"binance_trades temizlendi ({n} satır silindi). Dashboard sıfır.")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Binance testnet flat + dashboard reset")
    ap.add_argument("--wipe-db", action="store_true",
                    help="binance_trades tablosunu da temizle")
    ap.add_argument("--yes", action="store_true", help="onay sorma")
    args = ap.parse_args()

    client = BinanceTestClient()
    if not client.has_credentials():
        print("HATA: BINANCE_API_KEY / BINANCE_SECRET env gerekli.", file=sys.stderr)
        return 1
    if not client.ping_auth():
        print("HATA: Binance testnet kimlik doğrulanamadı.", file=sys.stderr)
        return 1

    if not args.yes:
        extra = " + binance_trades silinecek" if args.wipe_db else ""
        ans = input(f"TÜM açık pozisyon kapatılacak + emirler iptal{extra}. "
                    f"Devam? [evet/HAYIR]: ").strip().lower()
        if ans not in ("evet", "e", "yes", "y"):
            print("İptal edildi.")
            return 1

    _flatten(client)
    if args.wipe_db:
        _wipe_db()
    client.close()
    print("Bitti — borsa düzleştirildi" + (" + dashboard sıfırlandı." if args.wipe_db
                                           else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
