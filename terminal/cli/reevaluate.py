"""Mevcut setup'ları MEXC tarihsel verisiyle yeniden değerlendir (backfill).

Eski sürümlerde `register_new` D pivot sonrası mumları tek tek işlemiyordu,
sadece "son mum" üzerinden karar veriyordu. Bu yüzden tarihsel setup'lar
yanlış EO olarak işaretlenmiş olabilir (gerçekte fiyat PRZ'ye girip TP veya
STOP olmuş olabilir).

Bu komut DB'deki tüm setup'ları (veya filtrelenmiş alt küme) sırayla işler:
  1. Setup'ın D pivot zamanından bugüne kadar MEXC'den mumları çeker
  2. Lifecycle'ı sıfırdan kurar (eski state'i siler, baştan kayıt eder)
  3. backfill ile gerçek transition'ları (Aktif/TP/STOP/EO/ZI) uygular

Kullanım:
    python -m terminal.cli.reevaluate                       # tüm setup'lar
    python -m terminal.cli.reevaluate --symbol AVAXUSDT     # sadece AVAX
    python -m terminal.cli.reevaluate --state EO            # sadece EO'lar
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store
from terminal.lifecycle.tracker import LifecycleTracker

log = logging.getLogger(__name__)

# Interval → ms
_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1W": 604_800_000,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-reevaluate",
        description="Mevcut setup'ları MEXC tarihsel verisiyle yeniden değerlendir",
    )
    parser.add_argument("--symbol", help="Sadece bu parite")
    parser.add_argument("--interval", help="Sadece bu aralık")
    parser.add_argument("--state", help="Sadece bu durumdaki setup'lar (Aday/Aktif/EO/ZI/TP/STOP)")
    parser.add_argument("--padding", type=int, default=30,
                        help="D pivot sonrası ek mum (varsayılan 30)")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    store = Store()
    client = MexcClient()

    # Filtreli setup listesi
    sql = """SELECT s.id, s.symbol, s.interval, s.d_time
             FROM setups s LEFT JOIN setup_lifecycle l ON l.setup_id = s.id
             WHERE 1=1"""
    params: list = []
    if args.symbol:
        sql += " AND s.symbol = ?"; params.append(args.symbol.upper())
    if args.interval:
        sql += " AND s.interval = ?"; params.append(args.interval)
    if args.state:
        sql += " AND l.state = ?"; params.append(args.state)
    sql += " ORDER BY s.d_time"
    rows = store._conn.execute(sql, params).fetchall()
    if not rows:
        print("Eşleşen setup yok.", file=sys.stderr)
        store.close(); client.close()
        return 1

    print(f"\n{len(rows)} setup yeniden değerlendiriliyor...\n")
    changed = 0
    for r in rows:
        sid, sym, iv, d_time = int(r[0]), r[1], r[2], int(r[3])
        setup = store.load_setup(sid)
        if setup is None:
            continue

        # MEXC'den D pivot zamanına kadar olan + sonrasındaki mumları çek
        interval_ms = _INTERVAL_MS.get(iv, 3_600_000)
        now_ms = int(time.time() * 1000)
        bars_since_d = max(50, (now_ms - d_time) // interval_ms + args.padding)
        bars_to_fetch = bars_since_d + 50  # D öncesinden bir miktar tampon
        try:
            klines = client.klines_paginated(sym, iv, min(int(bars_to_fetch), 5000), throttle=0.05)
        except MexcError as e:
            print(f"  {sym} {iv} setup#{sid}: MEXC hatası — atlanıyor ({e})")
            continue

        # Klines'ı D pivot'tan itibaren olacak şekilde kırp (gereksiz değil ama düzen için)
        klines = [k for k in klines if k["open_time"] >= d_time - 5 * interval_ms]
        if not any(k["open_time"] == d_time for k in klines):
            print(f"  {sym} {iv} setup#{sid}: D pivot mum dizisinde yok — atlanıyor")
            continue

        # Eski lifecycle/events sil
        old_state = None
        old = store.get_lifecycle(sid)
        if old:
            old_state = old["state"]
            store._conn.execute("DELETE FROM setup_lifecycle WHERE setup_id = ?", (sid,))
            store._conn.execute("DELETE FROM setup_events WHERE setup_id = ?", (sid,))

        # Yeniden register (backfill ile)
        tracker = LifecycleTracker(sym, iv, store, on_transition=None)
        tracker.register_new(setup, sid, klines=klines)

        new = store.get_lifecycle(sid)
        new_state = new["state"] if new else "?"
        if old_state != new_state:
            changed += 1
            print(f"  {sym:<12} {iv:<4} setup#{sid}: {old_state} → {new_state}")

    print(f"\n{changed}/{len(rows)} setup değişti.")
    store.close()
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
