"""Setups + lifecycle'da duplicate aramak ve temizlemek."""
from terminal.db.store import Store

s = Store()
print("=== Aynı (symbol, interval, pattern, X-A-B-C-D zamanları) ile 2+ kayıt ===\n")
cur = s._conn.execute(
    """SELECT symbol, interval, pattern_name,
              x_time, a_time, b_time, c_time, d_time,
              COUNT(*) AS n, GROUP_CONCAT(id) AS ids
       FROM setups
       GROUP BY symbol, interval, pattern_name,
                x_time, a_time, b_time, c_time, d_time
       HAVING COUNT(*) > 1"""
)
rows = cur.fetchall()
if not rows:
    print("Yok — UNIQUE constraint çalışıyor.")
else:
    print(f"{len(rows)} duplicate grubu bulundu:")
    for r in rows:
        print(f"  {r[0]} {r[1]} {r[2]} | D={r[7]} | x{r[8]} kez | ids={r[9]}")

print("\n=== ms-yakın (≤30sn fark) potansiyel duplicate'ler ===\n")
cur = s._conn.execute(
    """SELECT a.symbol, a.interval, a.pattern_name,
              a.id AS id_a, b.id AS id_b,
              a.d_time AS d_a, b.d_time AS d_b,
              a.q_score AS qa, b.q_score AS qb
       FROM setups a
       JOIN setups b ON a.symbol = b.symbol AND a.interval = b.interval
                    AND a.pattern_name = b.pattern_name
                    AND a.direction = b.direction
                    AND a.id < b.id
                    AND ABS(a.d_time - b.d_time) < 30000
                    AND ABS(a.entry - b.entry) / a.entry < 0.001
       LIMIT 50"""
)
rows = cur.fetchall()
if not rows:
    print("Yok.")
else:
    print(f"{len(rows)} yakın-duplicate çift bulundu:")
    for r in rows:
        diff_ms = abs(r[5] - r[6])
        print(f"  {r[0]} {r[1]} {r[2]} | id_a={r[3]} id_b={r[4]} "
              f"D fark={diff_ms}ms | Q: {r[7]}/{r[8]}")

print("\n=== TEMİZLEMEK İSTERSEN: ===")
print("python -c \"from terminal.db.store import Store; "
      "Store()._conn.execute('DELETE FROM setups WHERE id IN (SELECT MIN(id) "
      "FROM setups GROUP BY symbol, interval, pattern_name, x_time, a_time, "
      "b_time, c_time, d_time HAVING COUNT(*) > 1)').rowcount\"")
