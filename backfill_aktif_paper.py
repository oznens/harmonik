"""Şu an AKTIF olan setupları paper'a aç — ileriye dönük takip.

'Şu anki Aktifleri aç' modu: yalnızca lifecycle.state='Aktif' (halen açık)
setuplar için paper pozisyon açar. Geçmiş TP/STOP setuplarına DOKUNMAZ,
sahte P&L üretmez — equity başlangıçta kalır, trade'ler ileriye doğru
gerçek sonuçla kapanır.

Idempotent: zaten paper_trades'te olan setupları atlar.

Kullanım:
    python backfill_aktif_paper.py
"""
from datetime import datetime, timedelta, timezone

from terminal.db.store import Store
from terminal.paper.engine import PaperEngine

TZ = timezone(timedelta(hours=3))


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M") if ms else "—"


def main() -> int:
    s = Store()
    pe = PaperEngine(s)

    rows = s._conn.execute("""
        SELECT s.id
        FROM setups s
        JOIN setup_lifecycle l ON l.setup_id = s.id
        WHERE l.state = 'Aktif' AND s.elenen = 0
        ORDER BY l.entered_at ASC
    """).fetchall()
    ids = [r[0] for r in rows]
    print(f"Halen Aktif setup: {len(ids)}\n")

    opened = 0
    skipped = 0
    for sid in ids:
        chk = s._conn.execute(
            "SELECT 1 FROM paper_trades WHERE setup_id = ?", (sid,)
        ).fetchone()
        if chk is not None:
            skipped += 1
            continue
        setup = s.load_setup(sid)
        if setup is None:
            skipped += 1
            continue
        life = s.get_lifecycle(sid)
        opened_at = (life["entered_at"] if life and life["entered_at"]
                     else setup.detected_at)
        trade = pe.open_trade(setup, sid, opened_at)
        if trade is None:
            skipped += 1
            continue
        opened += 1
        print(f"  + #{sid} {setup.symbol} {setup.interval} {setup.pattern_name} "
              f"{setup.direction} pos=${trade.position_usd:.0f} "
              f"lev={trade.leverage:.0f}x  ({_fmt(opened_at)})")

    summary = pe.summary()
    print(f"\n✓ Açılan: {opened}  |  Atlandı (zaten var / geçersiz): {skipped}")
    print(f"Equity: ${summary['initial_equity']:.0f} → "
          f"${summary['current_equity']:.2f}  |  açık paper trade: {opened}")
    print("Bu pozisyonlar ileriye doğru gerçek TP/STOP ile kapanacak.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
