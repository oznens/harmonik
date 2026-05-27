"""Paper trade alanını sıfırla — setup/lifecycle verisine DOKUNMAZ.

- paper_trades: tüm trade'ler silinir
- paper_account: equity → initial_equity, sayaçlar 0

Kullanım:
    python reset_paper.py              # default $1000 ile sıfırla
    python reset_paper.py --equity 500 # $500 ile sıfırla
"""
import argparse
import time

from terminal.db.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=1000.0,
                    help="Yeni başlangıç equity USD (default 1000)")
    ap.add_argument("--yes", action="store_true",
                    help="Onay sormadan sıfırla")
    args = ap.parse_args()

    s = Store()
    n_trades = s._conn.execute(
        "SELECT COUNT(*) FROM paper_trades"
    ).fetchone()[0]
    acc = s._conn.execute(
        "SELECT current_equity, total_trades, tp_count, stop_count, total_pnl "
        "FROM paper_account WHERE id = 1"
    ).fetchone()

    print("=== MEVCUT DURUM ===")
    if acc:
        eq, tot, tp, stp, pnl = acc
        print(f"Equity: ${eq:.2f}  |  Trade: {tot} (TP {tp} / STOP {stp})  "
              f"|  P&L: ${pnl:+.2f}")
    print(f"paper_trades kayıt sayısı: {n_trades}")
    print(f"\nSıfırlanacak: paper_trades + paper_account "
          f"→ equity ${args.equity:.0f}\n")

    if not args.yes:
        resp = input("Devam? (yes/hayır): ").strip().lower()
        if resp not in ("yes", "y", "evet", "e"):
            print("İptal.")
            return 1

    s._conn.execute("DELETE FROM paper_trades")
    s._conn.execute("DELETE FROM sqlite_sequence WHERE name='paper_trades'")
    s._conn.execute(
        """UPDATE paper_account
           SET initial_equity = ?, current_equity = ?,
               total_trades = 0, tp_count = 0, stop_count = 0,
               total_pnl = 0, created_at = ?
           WHERE id = 1""",
        (args.equity, args.equity, int(time.time() * 1000)),
    )
    if s._conn.execute("SELECT COUNT(*) FROM paper_account").fetchone()[0] == 0:
        s._conn.execute(
            "INSERT INTO paper_account (id, initial_equity, current_equity, "
            "total_trades, tp_count, stop_count, total_pnl, created_at) "
            "VALUES (1, ?, ?, 0, 0, 0, 0, ?)",
            (args.equity, args.equity, int(time.time() * 1000)),
        )
    s._conn.commit()
    print(f"\n✓ Sıfırlandı. Yeni equity: ${args.equity:.2f}")
    print("Tracker --paper ile çalışıyorsa, yeni AKTIF setup'lar "
          "buradan trade açacak.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
