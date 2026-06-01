"""OKX demo hesabını TAM düzleştir + (opsiyonel) dashboard verisini sıfırla.

Tek seferlik reset aracı ("siteyi sıfırla"):
  1) Tüm açık SWAP pozisyonlarını market ile kapat (autoCxl → iliştirilmiş
     TP/SL de iptal olur).
  2) Bekleyen (dolmamış) normal limit emirleri iptal et.
  3) Kalan bekleyen algo (OCO/conditional) emirleri iptal et.
  4) --wipe-db: okx_trades tablosunu temizle (dashboard sıfırlanır). Paper'ın
     paylaştığı setups tablosuna DOKUNMAZ.

ÖNCE servisi durdur (DB kilidi + re-sync çakışmasın):
    sudo systemctl stop harmonik-okx
Sonra (kimlik drop-in'den env'e enjekte edilerek) çalıştır, en son servisi başlat.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from terminal.config import DB_PATH
from terminal.data.okx_trade import OkxAuthError, OkxDemoClient


def _flatten(client: OkxDemoClient) -> None:
    # 1) Açık pozisyonları kapat (pos=0 olanları atla)
    pos = [p for p in client.positions() if _f(p.get("pos")) != 0.0]
    print(f"Açık pozisyon: {len(pos)}")
    for p in pos:
        inst = p.get("instId", "")
        mgn = p.get("mgnMode", "cross")
        side = p.get("posSide")
        try:
            client.close_position(inst, mgn,
                                  side if side in ("long", "short") else None)
            print(f"  kapatıldı: {inst} ({mgn})")
        except OkxAuthError as e:
            print(f"  ATLA kapat {inst}: {e}")

    # 2) Bekleyen normal emirler (dolmamış resting limitler)
    ords = client.orders_pending()
    print(f"Bekleyen emir: {len(ords)}")
    for o in ords:
        inst, oid = o.get("instId", ""), o.get("ordId", "")
        try:
            client.cancel_order(inst, oid)
            print(f"  iptal emir: {inst} {oid}")
        except OkxAuthError as e:
            print(f"  ATLA emir {inst} {oid}: {e}")

    # 3) Kalan bekleyen algo emirler (öksüz OCO/conditional)
    for ot in ("oco", "conditional"):
        algos = client.algo_pending(ord_type=ot)
        if algos:
            print(f"Bekleyen algo ({ot}): {len(algos)}")
        for a in algos:
            inst, aid = a.get("instId", ""), a.get("algoId", "")
            try:
                client.cancel_algo(inst, aid, ord_type=ot)
                print(f"  iptal algo: {inst} {aid}")
            except OkxAuthError as e:
                print(f"  ATLA algo {inst} {aid}: {e}")


def _f(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _wipe_db() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        try:
            n = conn.execute("SELECT COUNT(*) FROM okx_trades").fetchone()[0]
        except sqlite3.OperationalError:
            print("okx_trades tablosu yok — DB temizliği atlandı.")
            return
        conn.execute("DELETE FROM okx_trades")
        conn.commit()
        print(f"okx_trades temizlendi ({n} satır silindi). Dashboard sıfır.")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="OKX demo flat + dashboard reset")
    ap.add_argument("--wipe-db", action="store_true",
                    help="okx_trades tablosunu da temizle (dashboard sıfırlanır)")
    ap.add_argument("--yes", action="store_true",
                    help="onay sorma (zaten onaylandıysa)")
    args = ap.parse_args()

    client = OkxDemoClient()
    if not client.has_credentials():
        print("HATA: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE env gerekli.",
              file=sys.stderr)
        return 1
    if not client.ping_auth():
        print("HATA: OKX demo kimlik doğrulanamadı (anahtar/passphrase?).",
              file=sys.stderr)
        return 1

    if not args.yes:
        extra = " + okx_trades silinecek" if args.wipe_db else ""
        ans = input(f"TÜM açık demo pozisyon kapatılacak + bekleyen emirler "
                    f"iptal{extra}. Devam? [evet/HAYIR]: ").strip().lower()
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
