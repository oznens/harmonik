"""Paper trade açılma kontrolü — AKTIF setup'lar vs paper_trades."""
from datetime import datetime, timedelta, timezone
from terminal.db.store import Store

TZ = timezone(timedelta(hours=3))
def fmt(ms): return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M") if ms else "—"

s = Store()
print("=== Son 30 AKTIF/TP/STOP setup (lifecycle) ===\n")
cur = s._conn.execute("""
    SELECT s.id, s.symbol, s.interval, s.pattern_name, s.direction, s.entry, s.stop, s.tp1,
           s.elenen, s.confluence_score, l.state, l.entered_at,
           pt.id AS pt_id, pt.position_usd, pt.outcome AS pt_outcome
    FROM setups s
    JOIN setup_lifecycle l ON l.setup_id = s.id
    LEFT JOIN paper_trades pt ON pt.setup_id = s.id
    WHERE l.state IN ('Aktif', 'TP', 'STOP', 'EO', 'ZI')
      AND s.elenen = 0
    ORDER BY l.entered_at DESC NULLS LAST, s.detected_at DESC
    LIMIT 30
""")
rows = cur.fetchall()
if not rows:
    print("Hiç AKTIF/exit setup yok.")
else:
    print(f"{'id':>4s} {'parite':10s} {'TF':4s} {'pattern':14s} {'state':6s} "
          f"{'conf':>4s} {'paper':>8s}  entered_at")
    for r in rows:
        (sid, sym, ivl, pat, dirn, e, sl, tp, el, conf, state, ea,
         pt_id, pt_pos, pt_out) = r
        paper_str = f"#{pt_id}" if pt_id else "—YOK—"
        if pt_out:
            paper_str = f"#{pt_id}({pt_out})"
        print(f"{sid:4d} {sym:10s} {ivl:4s} {pat:14s} {state:6s} "
              f"{(conf or 0):>4d} {paper_str:>8s}  {fmt(ea)}")

# Paper engine summary
print("\n=== PAPER ACCOUNT ===")
cur = s._conn.execute(
    "SELECT initial_equity, current_equity, total_trades, tp_count, stop_count, total_pnl "
    "FROM paper_account WHERE id = 1"
).fetchone()
if cur:
    print(f"Equity: ${cur[0]:.0f} → ${cur[1]:.2f}  |  Trade: {cur[2]} "
          f"(TP {cur[3]} / STOP {cur[4]})  |  Toplam P&L: ${cur[5]:+.2f}")
else:
    print("paper_account satırı yok — PaperEngine init olmamış (sistem --paper ile başlamamış!)")

# Açık paper trade'ler
print("\n=== AÇIK PAPER TRADELER ===")
cur = s._conn.execute("""
    SELECT pt.id, pt.symbol, pt.interval, pt.pattern, pt.direction,
           pt.entry_price, pt.position_usd, pt.leverage, pt.opened_at
    FROM paper_trades pt
    WHERE pt.closed_at IS NULL
    ORDER BY pt.opened_at DESC
""")
rows = cur.fetchall()
if not rows:
    print("Yok.")
else:
    for r in rows:
        print(f"  #{r[0]} {r[1]} {r[2]} {r[3]} {r[4]} entry=${r[5]:.6g} "
              f"pos=${r[6]:.0f} lev={r[7]:.0f}x opened={fmt(r[8])}")
