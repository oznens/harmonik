"""Faz 2 giriş noktası: canlı veri + her kapanan mumda formasyon taraması.

Kullanım:
    python -m terminal.cli.run_live --symbol BTCUSDT --interval 1h
    python -m terminal.cli.run_live --symbol ETHUSDT --interval 15m --zigzag 0.012
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Any

from terminal.cli.run_data import _normalize_interval
from terminal.data.kline_poller import KlinePoller
from terminal.data.mexc_client import MexcClient
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines

log = logging.getLogger(__name__)


def _fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-live",
        description="terminalMiraz — Faz 2 (canlı veri + formasyon tespit)",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--zigzag", type=float, default=None,
                        help="ZigZag yüzde eşiği. Yoksa interval'a göre varsayılan.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbol = args.symbol.upper().strip()
    interval = _normalize_interval(args.interval)
    threshold = args.zigzag if args.zigzag is not None else default_threshold(interval)

    client = MexcClient()
    store = Store()
    if not client.ping():
        log.error("MEXC ping başarısız.")
        return 1

    # Aynı setup'ı her kapanan mumda tekrar log'lamamak için son görülen pivot'ları tut.
    seen_keys: set[tuple] = set()

    def scan_and_store(_closed: dict[str, Any] | None) -> None:
        klines = poller.buffer.as_list()
        if len(klines) < 20:
            return
        setups = scan_klines(klines, symbol, interval, zigzag_threshold=threshold)
        if not setups:
            return

        setups.sort(key=lambda s: s.pivots["D"].time, reverse=True)
        new_count = 0
        for s in setups:
            key = (s.pattern_name,
                   s.pivots["X"].time, s.pivots["A"].time,
                   s.pivots["B"].time, s.pivots["C"].time, s.pivots["D"].time)
            is_new = key not in seen_keys
            seen_keys.add(key)
            store.upsert_setup(s)
            if is_new:
                new_count += 1
                d_time = s.pivots["D"].time
                # Son 3 mumda D oluştuysa "YENİ", değilse tarihsel
                tag = "YENI" if d_time >= klines[-3]["open_time"] else "TARIHSEL"
                log.info("[%s] %s | D@%s", tag, s.summary(), _fmt(d_time))

        if new_count == 0:
            log.debug("Tarama tamam, yeni formasyon yok (%d toplam).", len(setups))

    poller = KlinePoller(symbol, interval, client, store, on_closed=scan_and_store)

    def shutdown(signum, frame):  # noqa: ARG001
        log.info("Kapatma sinyali alındı...")
        poller.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        poller.bootstrap()
        log.info("İlk tarama (bootstrap sonrası, ZigZag eşik=%.4f)...", threshold)
        scan_and_store(None)
        log.info("Canlı polling başlıyor — her kapanan mumda yeniden taranacak.")
        poller.poll_loop()
    finally:
        client.close()
        total = store.count_setups(symbol, interval)
        store.close()
        log.info("Temiz kapanış. DB'de toplam %d setup (%s %s).", total, symbol, interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
