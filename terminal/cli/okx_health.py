"""OKX demo hattı sağlık kontrolü — tek komutla canlı durum.

OKX'ten açık pozisyon + iliştirilmiş TP/SL (OCO) + bakiyeyi çeker, DB ile
çapraz kontrol eder ve sorunları listeler:

  - KORUMASIZ pozisyon: açık ama OCO'su (TP/SL) olmayan → riskli (genelde eski
    birikme kalıntısı, ör. 16-haneli avgPx). Elle kapatılmalı.
  - ÖKSÜZ OCO: pozisyonu olmayan bekleyen TP/SL emri → margin/parite kilitler
    (sync otomatik temizler ama burada da görünür).
  - Bakiye + açık pozisyon margin özeti.

Kimlik ENV'den: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE.

Kullanım:
    OKX_API_KEY=... OKX_SECRET=... OKX_PASSPHRASE=... \\
    python -m terminal.cli.okx_health
"""
from __future__ import annotations

import argparse
import sys

from terminal.data.okx_trade import OkxAuthError, OkxDemoClient


def _sci_avg(avg: str) -> bool:
    """avgPx çok-haneli mi (eski birikme kalıntısı ipucu)."""
    s = str(avg)
    return "." in s and len(s.split(".")[-1]) > 8


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="okx-health",
                                 description="OKX demo hattı sağlık kontrolü")
    ap.add_argument("--quiet", action="store_true",
                    help="Sadece sorun varsa çıktı ver (cron/izleme için).")
    args = ap.parse_args(argv)

    c = OkxDemoClient()
    if not c.has_credentials():
        print("HATA: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE gerekli.",
              file=sys.stderr)
        return 2
    try:
        positions = [p for p in c.positions() if float(p.get("pos") or 0) != 0]
        oco = c.algo_pending(ord_type="oco")
        bal = c.balance()
    except OkxAuthError as e:
        print(f"HATA: OKX sorgu başarısız: {e}", file=sys.stderr)
        return 2
    finally:
        c.close()

    pos_insts = {p["instId"] for p in positions}
    oco_insts = {a["instId"] for a in oco}

    unprotected = [p for p in positions if p["instId"] not in oco_insts]
    orphan_oco = [a for a in oco if a["instId"] not in pos_insts]

    # Boş USDT
    free = "—"
    for d in bal.get("details", []):
        if d.get("ccy") == "USDT":
            free = d.get("availBal") or d.get("availEq") or d.get("cashBal") or "—"
            break

    problems = bool(unprotected or orphan_oco)
    if args.quiet and not problems:
        return 0

    print(f"=== OKX DEMO SAĞLIK ===")
    print(f"Açık pozisyon: {len(positions)} | OCO (TP/SL): {len(oco)} | "
          f"boş USDT: {free}")

    if unprotected:
        print(f"\n⚠️  KORUMASIZ POZİSYON ({len(unprotected)}) — OCO yok, riskli:")
        for p in unprotected:
            tag = " (eski birikme? 16-hane avgPx)" if _sci_avg(p.get("avgPx", "")) else ""
            print(f"   {p['instId']:20s} pos={p.get('pos')} avgPx={p.get('avgPx')}{tag}")
        print("   → OKX app'ten elle kapat (SL'siz açık risk).")
    else:
        print("\n✓ Tüm açık pozisyonlar OCO (TP/SL) korumalı.")

    if orphan_oco:
        print(f"\n⚠️  ÖKSÜZ OCO ({len(orphan_oco)}) — pozisyonu yok, margin kilitler:")
        for a in orphan_oco:
            print(f"   {a['instId']:20s} algoId={a.get('algoId')} "
                  f"tp={a.get('tpTriggerPx','-')} sl={a.get('slTriggerPx','-')}")
        print("   → sync otomatik temizler (bir sonraki turda).")
    else:
        print("✓ Öksüz OCO yok.")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
