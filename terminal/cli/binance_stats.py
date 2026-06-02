"""Binance testnet performans özeti — terminal raporu (salt-okunur).

binance_trades tablosunu okur: açık/kapalı, TP/STOP, WR, P&L, pattern & TF
kırılımı, en iyi/kötü işlemler. Dashboard'a gerek kalmadan hızlı bakış.

Kullanım:
    python -m terminal.cli.binance_stats
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from terminal.config import DB_PATH


def _wr(tp: int, sl: int) -> float:
    return tp / (tp + sl) * 100 if (tp + sl) else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Binance testnet performans özeti")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e:
        print(f"DB açılamadı: {e}", file=sys.stderr)
        return 1
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name='binance_trades'").fetchone() is None:
            print("binance_trades tablosu yok (henüz işlem açılmamış).")
            return 0

        op = conn.execute("SELECT COUNT(*) FROM binance_trades "
                          "WHERE closed_at IS NULL").fetchone()[0]
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(pnl_usd>0),0), COALESCE(SUM(pnl_usd<0),0), "
            "COALESCE(SUM(pnl_usd),0), COALESCE(AVG(pnl_usd),0) "
            "FROM binance_trades WHERE state='closed'").fetchone()
        cl, tp, sl, pnl, avg = row
        wr = _wr(tp, sl)
        sign = "+" if pnl >= 0 else ""

        print("=" * 52)
        print(f"  BINANCE TESTNET — PaMonic performansı")
        print("=" * 52)
        print(f"  Açık pozisyon : {op}")
        print(f"  Kapanan       : {cl}  (TP {tp} / STOP {sl})")
        print(f"  Win Rate      : {wr:.1f}%")
        print(f"  Toplam P&L    : {sign}${pnl:.2f}   (ort. ${avg:.3f}/işlem)")
        print("-" * 52)

        pats = conn.execute(
            "SELECT pattern, SUM(pnl_usd>0) tp, SUM(pnl_usd<0) sl, "
            "COALESCE(SUM(pnl_usd),0) pnl FROM binance_trades WHERE state='closed' "
            "GROUP BY pattern ORDER BY pnl DESC").fetchall()
        if pats:
            print("  PATTERN         TP/STOP   WR     P&L")
            for p in pats:
                t, s = p["tp"] or 0, p["sl"] or 0
                print(f"  {p['pattern'][:14]:14s}  {t:>3}/{s:<3}  {_wr(t,s):4.0f}%  "
                      f"{'+' if p['pnl']>=0 else ''}${p['pnl']:.2f}")
            print("-" * 52)

        tfs = conn.execute(
            "SELECT interval, SUM(pnl_usd>0) tp, SUM(pnl_usd<0) sl, "
            "COALESCE(SUM(pnl_usd),0) pnl FROM binance_trades WHERE state='closed' "
            "GROUP BY interval ORDER BY pnl DESC").fetchall()
        if tfs:
            print("  TF      TP/STOP   WR     P&L")
            for t in tfs:
                a, b = t["tp"] or 0, t["sl"] or 0
                print(f"  {t['interval']:6s}  {a:>3}/{b:<3}  {_wr(a,b):4.0f}%  "
                      f"{'+' if t['pnl']>=0 else ''}${t['pnl']:.2f}")
            print("-" * 52)

        best = conn.execute(
            "SELECT symbol, interval, pattern, pnl_usd FROM binance_trades "
            "WHERE state='closed' ORDER BY pnl_usd DESC LIMIT 3").fetchall()
        worst = conn.execute(
            "SELECT symbol, interval, pattern, pnl_usd FROM binance_trades "
            "WHERE state='closed' ORDER BY pnl_usd ASC LIMIT 3").fetchall()
        if best:
            print("  EN İYİ 3:")
            for r in best:
                print(f"    {r['symbol']:10s} {r['interval']:4s} {r['pattern'][:12]:12s} "
                      f"+${r['pnl_usd']:.2f}")
        if worst:
            print("  EN KÖTÜ 3:")
            for r in worst:
                print(f"    {r['symbol']:10s} {r['interval']:4s} {r['pattern'][:12]:12s} "
                      f"${r['pnl_usd']:.2f}")
        print("=" * 52)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
