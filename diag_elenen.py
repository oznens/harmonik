"""DB'deki elenen + lifecycle tutarsızlıklarını rapor et."""
from terminal.db.store import Store

s = Store()
print("=== ELENEN setup'lar + lifecycle durumu ===\n")
cur = s._conn.execute(
    """SELECT s.id, s.symbol, s.interval, s.pattern_name, s.direction, s.elenen,
              s.htf_aligned, l.state
       FROM setups s
       LEFT JOIN setup_lifecycle l ON l.setup_id = s.id
       WHERE s.elenen = 1
       ORDER BY s.symbol, s.interval"""
)
rows = cur.fetchall()
if not rows:
    print("Hiç elenen=1 setup yok.")
else:
    print(f"Toplam elenen={len(rows)}:")
    for r in rows:
        sid, sym, ivl, pat, dirn, el, ha, state = r
        print(f"  id={sid:4d} {sym:10s} {ivl:4s} {pat:18s} {dirn:5s} "
              f"htf_aligned={ha} state={state}")

print("\n=== 1.62 AB=CD + HTF zıt olan AMA elenen=0 olan setuplar (HATA!) ===\n")
cur = s._conn.execute(
    """SELECT s.id, s.symbol, s.interval, s.pattern_name, s.direction, s.elenen,
              s.htf_aligned, l.state
       FROM setups s
       LEFT JOIN setup_lifecycle l ON l.setup_id = s.id
       WHERE s.pattern_name = '1.62 AB=CD' AND s.htf_aligned = 0 AND s.elenen = 0"""
)
rows = cur.fetchall()
if not rows:
    print("Yok — tüm 1.62 AB=CD + HTF zıt olanlar elenen=1.")
else:
    print(f"{len(rows)} HATALI kayıt (elenen yanlış):")
    for r in rows:
        sid, sym, ivl, pat, dirn, el, ha, state = r
        print(f"  id={sid:4d} {sym:10s} {ivl:4s} state={state}")

print("\n=== Aday/Aktif state'inde olan elenen setupları (HATA!) ===\n")
cur = s._conn.execute(
    """SELECT s.symbol, s.interval, s.pattern_name, l.state, s.elenen
       FROM setups s
       JOIN setup_lifecycle l ON l.setup_id = s.id
       WHERE s.elenen = 1 AND l.state IN ('Aday', 'Aktif')"""
)
rows = cur.fetchall()
if not rows:
    print("Yok — elenen setuplarda lifecycle (Aday/Aktif) yok.")
else:
    print(f"{len(rows)} HATALI kayıt (elenen ama aktif):")
    for r in rows:
        print(f"  {r[0]:10s} {r[1]:4s} {r[2]:18s} state={r[3]}")
