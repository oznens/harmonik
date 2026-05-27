"""Mevcut AKTIF/TP/STOP setupları için bir defaya mahsus paper trade üret.

Tracker --paper ile yeniden başladığında, sistemde önceden işlenmiş
setup'lar paper_trades tablosunda yok. Bu script onları doldurur:
- AKTIF setup → açık paper trade
- TP/STOP setup → kapalı paper trade (P&L hesaplanır)

Idempotent: paper_trades'te zaten kayıtlı setupları atlar.
"""
from terminal.db.store import Store
from terminal.paper.engine import PaperEngine, compute_position, COMMISSION_PCT
from terminal.detection.models import Setup

s = Store()
pe = PaperEngine(s)

# Tüm lifecycle'da TP/STOP/EO/ZI/Aktif olan setup'ları al
cur = s._conn.execute("""
    SELECT s.id, s.symbol, s.interval, s.pattern_name, s.direction,
           s.entry, s.stop, s.tp1, s.detected_at,
           l.state, l.entered_at, l.exited_at,
           (SELECT trigger_price FROM setup_events WHERE setup_id = s.id
            AND new_state IN ('TP','STOP','EO','ZI')
            ORDER BY event_time DESC LIMIT 1) AS exit_price
    FROM setups s
    JOIN setup_lifecycle l ON l.setup_id = s.id
    WHERE l.state IN ('TP','STOP','EO','ZI','Aktif')
      AND s.elenen = 0
    ORDER BY s.detected_at ASC
""")
rows = cur.fetchall()

print(f"İşlenecek: {len(rows)} setup\n")
opened = 0
closed = 0
skipped = 0

for r in rows:
    (sid, sym, ivl, pat, dirn, entry, stop, tp1, det,
     state, ea, xa, exit_price) = r

    # Zaten paper'da var mı?
    chk = s._conn.execute(
        "SELECT closed_at FROM paper_trades WHERE setup_id = ?", (sid,)
    ).fetchone()
    if chk is not None:
        skipped += 1
        continue

    # Pozisyon hesabı
    equity = pe.get_equity()
    position, leverage = compute_position(entry, stop, equity, pe.risk_per_trade)
    if position <= 0:
        skipped += 1
        continue

    opened_at = ea if ea else det
    s._conn.execute(
        """INSERT INTO paper_trades
           (setup_id, symbol, interval, pattern, direction,
            entry_price, stop_price, tp1_price,
            position_usd, leverage, risk_usd, opened_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, sym, ivl, pat, dirn, entry, stop, tp1,
         position, leverage, pe.risk_per_trade, opened_at),
    )
    opened += 1

    # Kapalıysa P&L hesapla
    if state in ("TP", "STOP", "EO", "ZI"):
        if state == "TP":
            pnl_gross = position * abs(tp1 - entry) / entry
        elif state == "STOP":
            pnl_gross = -position * abs(entry - stop) / entry
        else:
            pnl_gross = 0.0
        commission = (position * COMMISSION_PCT * 2
                      if state in ("TP", "STOP") else 0.0)
        pnl_net = round(pnl_gross - commission, 2)
        ex_p = exit_price if exit_price else (tp1 if state == "TP"
                                              else stop if state == "STOP" else entry)
        closed_at = xa if xa else opened_at
        s._conn.execute(
            """UPDATE paper_trades
               SET closed_at = ?, exit_price = ?, outcome = ?, pnl_usd = ?
               WHERE setup_id = ?""",
            (closed_at, ex_p, state, pnl_net, sid),
        )
        # Account güncelle
        delta_tp = 1 if state == "TP" else 0
        delta_stop = 1 if state == "STOP" else 0
        s._conn.execute(
            """UPDATE paper_account
               SET current_equity = current_equity + ?,
                   total_trades = total_trades + 1,
                   tp_count = tp_count + ?,
                   stop_count = stop_count + ?,
                   total_pnl = total_pnl + ?
               WHERE id = 1""",
            (pnl_net, delta_tp, delta_stop, pnl_net),
        )
        closed += 1

print(f"\n✓ Açılan: {opened}  |  Kapanan (P&L'li): {closed}  |  Atlandı: {skipped}")
summary = pe.summary()
print(f"\n=== YENİ ACCOUNT DURUMU ===")
print(f"Equity: ${summary['initial_equity']:.0f} → ${summary['current_equity']:.2f}")
print(f"Toplam P&L: ${summary['total_pnl']:+.2f}  ({summary['pnl_pct']:+.1f}%)")
print(f"Trade: {summary['total_trades']}  (TP {summary['tp']} / STOP {summary['stop']})")
print(f"WR: {summary['win_rate']:.1f}%")
