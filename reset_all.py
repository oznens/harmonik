"""TEMİZ BAŞLANGIÇ — setup + lifecycle + paper alanını sıfırla.

Siler: setups, setup_lifecycle, setup_events, paper_trades, potential_patterns.
Sıfırlar: paper_account → initial_equity.
DOKUNMAZ: klines (mum cache — bootstrap hızlansın), karakter_* (backtest lab
verisi), journal.

Yani tracker yeniden başlayınca SIFIRDAN tarar; sadece bundan sonraki canlı
setup'lar ve (limit) paper trade'ler kaydedilir.

Kullanım:
    python reset_all.py                 # onay sorar, equity $1000
    python reset_all.py --yes           # sormadan
    python reset_all.py --equity 1000 --yes
"""
import argparse
import time

from terminal.db.store import Store

# Tamamen boşaltılacak tablolar (varsa)
WIPE_TABLES = [
    "setups", "setup_lifecycle", "setup_events",
    "paper_trades", "potential_patterns",
]


def _count(conn, table: str) -> int | None:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return None  # tablo yok


def main() -> int:
    ap = argparse.ArgumentParser(description="Setup + paper alanını sıfırla (temiz başlangıç)")
    ap.add_argument("--equity", type=float, default=1000.0,
                    help="Yeni başlangıç equity USD (default 1000)")
    ap.add_argument("--yes", action="store_true", help="Onay sormadan sıfırla")
    args = ap.parse_args()

    s = Store()
    c = s._conn

    print("=== MEVCUT DURUM ===")
    for t in WIPE_TABLES:
        n = _count(c, t)
        if n is not None:
            print(f"  {t:20s}: {n}")
    acc = c.execute(
        "SELECT current_equity, total_trades, total_pnl FROM paper_account WHERE id=1"
    ).fetchone()
    if acc:
        print(f"  paper_account       : equity ${acc[0]:.2f}, {acc[1]} trade, P&L ${acc[2]:+.2f}")
    kept = []
    for t in ("klines", "karakter_samples", "karakter_scores"):
        n = _count(c, t)
        if n is not None:
            kept.append(f"{t}={n}")
    print(f"\nKORUNACAK: {', '.join(kept) if kept else '—'}")
    print(f"SİLİNECEK: {', '.join(WIPE_TABLES)}  +  paper_account → ${args.equity:.0f}\n")

    if not args.yes:
        resp = input("Tüm setup/paper geçmişi silinsin mi? (yes/hayır): ").strip().lower()
        if resp not in ("yes", "y", "evet", "e"):
            print("İptal.")
            return 1

    for t in WIPE_TABLES:
        if _count(c, t) is None:
            continue
        c.execute(f"DELETE FROM {t}")
        try:
            c.execute("DELETE FROM sqlite_sequence WHERE name=?", (t,))
        except Exception:
            pass

    now = int(time.time() * 1000)
    c.execute(
        """UPDATE paper_account
           SET initial_equity=?, current_equity=?, total_trades=0,
               tp_count=0, stop_count=0, total_pnl=0, created_at=?
           WHERE id=1""",
        (args.equity, args.equity, now),
    )
    if c.execute("SELECT COUNT(*) FROM paper_account").fetchone()[0] == 0:
        c.execute(
            "INSERT INTO paper_account (id, initial_equity, current_equity, "
            "total_trades, tp_count, stop_count, total_pnl, created_at) "
            "VALUES (1, ?, ?, 0, 0, 0, 0, ?)",
            (args.equity, args.equity, now),
        )
    try:
        c.commit()
    except Exception:
        pass

    print(f"\n✓ TEMİZLENDİ. Yeni equity: ${args.equity:.2f}")
    print("Tracker'ı yeniden başlat → sıfırdan tarar, yeni setup/paper kaydedilir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
