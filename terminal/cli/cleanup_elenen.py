"""Elenen setupların yanlış oluşmuş lifecycle kayıtlarını temizle.

Önceki agresif-giriş davranışı elenen=True setupları yanlışlıkla AKTIF
state ile lifecycle'a yazmıştı. Bu komut o anomalileri siler.

Kullanım:
    python -m terminal.cli.cleanup_elenen
"""
from __future__ import annotations

from terminal.db.store import Store


def main() -> int:
    store = Store()
    cur = store._conn.execute(
        """SELECT COUNT(*) FROM setup_lifecycle
           WHERE setup_id IN (SELECT id FROM setups WHERE elenen = 1)"""
    )
    n = int(cur.fetchone()[0])
    if n == 0:
        print("Temizlenecek kayıt yok.")
        return 0
    print(f"{n} elenen setup'ın lifecycle kaydı bulundu.")
    store._conn.execute(
        """DELETE FROM setup_lifecycle
           WHERE setup_id IN (SELECT id FROM setups WHERE elenen = 1)"""
    )
    store._conn.execute(
        """DELETE FROM setup_events
           WHERE setup_id IN (SELECT id FROM setups WHERE elenen = 1)"""
    )
    print(f"✓ {n} lifecycle + ilgili event kayıtları silindi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
