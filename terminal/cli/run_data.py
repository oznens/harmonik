"""Faz 1 giriş noktası: tek bir parite × aralık için canlı veri akışı.

Kullanım:
    python -m terminal.cli.run_data --symbol BTCUSDT --interval 1h
    python -m terminal.cli.run_data --symbol ETHUSDT --interval 15m
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys

from terminal.config import INTERVAL_ALIASES, VALID_INTERVALS
from terminal.data.kline_poller import KlinePoller
from terminal.data.mexc_client import MexcClient
from terminal.db.store import Store


def _normalize_interval(interval: str) -> str:
    interval = interval.strip()
    interval = INTERVAL_ALIASES.get(interval, interval)
    if interval not in VALID_INTERVALS:
        valid = ", ".join(sorted(VALID_INTERVALS))
        raise SystemExit(
            f"Geçersiz aralık: {interval!r}. Geçerli değerler: {valid}"
        )
    return interval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-data",
        description="terminalMiraz — Faz 1 (veri akışı)",
    )
    parser.add_argument("--symbol", default="BTCUSDT", help="Parite (örn. BTCUSDT)")
    parser.add_argument(
        "--interval", default="1h",
        help="Mum aralığı: 1m, 5m, 15m, 30m, 1h/60m, 4h, 1d (varsayılan: 1h)",
    )
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbol = args.symbol.upper().strip()
    interval = _normalize_interval(args.interval)

    client = MexcClient()
    store = Store()

    if not client.ping():
        logging.error("MEXC ping başarısız. Ağ bağlantısı?")
        return 1

    poller = KlinePoller(symbol, interval, client, store)

    def shutdown(signum, frame):  # noqa: ARG001
        logging.info("Kapatma sinyali alındı, polling duruyor...")
        poller.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        poller.run()
    finally:
        client.close()
        store.close()
        logging.info("Temiz kapanış.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
