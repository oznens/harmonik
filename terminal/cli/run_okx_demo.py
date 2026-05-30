"""OKX Demo canlı hat — OKX veriyle tara, demo'ya gerçek emir at (paper'a paralel).

run_live_multi'nin OKX karşılığı; bağımsız tarayıcı. Her (parite × TF) worker:
OKX'ten mum çek → scan_klines → setup AKTIF olunca OkxDemoEngine.open_trade
(limit + TP/SL demo emri). Ayrı bir thread periyodik OkxDemoEngine.sync() çalıştırır
(emir/pozisyon durumu + realizedPnl).

Kimlik ENV'den: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE (demo trading anahtarı).

Kullanım:
    OKX_API_KEY=... OKX_SECRET=... OKX_PASSPHRASE=... \\
    python -m terminal.cli.run_okx_demo --combos-file config/tracked_combos.txt
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from terminal.cli.run_data import _normalize_interval
from terminal.data.okx_futures import OkxFuturesClient
from terminal.data.okx_instruments import OkxInstruments
from terminal.data.okx_trade import OkxDemoClient
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.lifecycle.tracker import LifecycleTracker
from terminal.paper.okx_engine import OkxDemoEngine
from terminal.quality.htf_ltf import htf_for

log = logging.getLogger(__name__)


def _load_combos(path: Path) -> list[tuple[str, str]]:
    combos = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            combos.append((parts[0].upper(), _normalize_interval(parts[1])))
    return combos


class OkxWorker:
    """Bir (parite, TF) için OKX veri tarayıcı + demo emir tetikleyici."""

    def __init__(self, symbol: str, interval: str, data: OkxFuturesClient,
                 store: Store, engine: OkxDemoEngine, poll_seconds: int,
                 startup_delay: float, use_htf: bool) -> None:
        self.symbol = symbol
        self.interval = interval
        self.data = data
        self.store = store
        self.engine = engine
        self.poll_seconds = poll_seconds
        self.startup_delay = startup_delay
        self.use_htf = use_htf
        self._running = False
        self._tag = f"[OKX {symbol} {interval}]"
        self._last_open: int | None = None

    def _on_transition(self, t) -> None:
        # Sadece AKTIF geçişinde demo emri at (paper'ın limit moduna benzer)
        if t.new_state == "Aktif" and t.setup_id is not None:
            if t.setup.elenen:
                return
            self.engine.open_trade(t.setup, t.setup_id, t.trigger_time)

    def run(self) -> None:
        time.sleep(self.startup_delay)
        tracker = LifecycleTracker(self.symbol, self.interval, self.store,
                                   on_transition=self._on_transition)
        thr = default_threshold(self.interval)
        self._running = True
        log.info("%s başladı (ZigZag %.4f)", self._tag, thr)
        while self._running:
            try:
                klines = self.data.klines(self.symbol, self.interval, limit=200)
                if len(klines) >= 20:
                    htf_klines = None
                    if self.use_htf and htf_for(self.interval):
                        try:
                            htf_klines = self.data.klines(self.symbol,
                                                          htf_for(self.interval), limit=120)
                        except Exception:
                            htf_klines = None
                    setups = scan_klines(klines, self.symbol, self.interval,
                                         zigzag_threshold=thr, htf_klines=htf_klines,
                                         target_mode="rr1", include_abcd=True)
                    for s in setups:
                        sid = self.store.upsert_setup(s)
                        if self.store.get_lifecycle(sid) is None:
                            tracker.register_new(s, sid, klines=klines)
                    tracker.advance(klines)
            except Exception as e:
                log.warning("%s döngü hatası: %s", self._tag, e)
            slept = 0.0
            while self._running and slept < self.poll_seconds:
                time.sleep(0.5); slept += 0.5

    def stop(self) -> None:
        self._running = False


def _sync_loop(engine: OkxDemoEngine, stop_event: threading.Event,
               interval: int) -> None:
    while not stop_event.is_set():
        try:
            n = engine.sync()
            if n:
                log.info("OKX SYNC: %d trade güncellendi | %s", n, engine.summary())
        except Exception as e:
            log.warning("OKX sync hatası: %s", e)
        stop_event.wait(interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-okx-demo",
        description="OKX demo canlı hat — OKX veriyle tara, demo'ya gerçek emir")
    ap.add_argument("--combos-file", required=True)
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--stagger-ms", type=int, default=300)
    ap.add_argument("--sync-seconds", type=int, default=30)
    ap.add_argument("--risk", type=float, default=20.0)
    ap.add_argument("--max-lever", type=int, default=50)
    ap.add_argument("--no-htf", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    combos = _load_combos(Path(args.combos_file))
    if not combos:
        print("HATA: combos boş.", file=sys.stderr)
        return 1

    # Kimlik kontrolü
    trade_client = OkxDemoClient()
    if not trade_client.has_credentials():
        print("HATA: OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE env gerekli.",
              file=sys.stderr)
        return 1
    if not trade_client.ping_auth():
        print("HATA: OKX demo kimlik doğrulanamadı (anahtar/passphrase?).",
              file=sys.stderr)
        return 1
    log.info("OKX demo bağlantı OK — bakiye: %s", trade_client.balance().get("totalEq"))

    Store().close()  # şema
    store = Store()
    instruments = OkxInstruments()
    engine = OkxDemoEngine(store, trade_client, instruments,
                           risk_per_trade=args.risk, max_lever=args.max_lever)

    log.info("OKX hat: %d kombinasyon, poll %ds, sync %ds",
             len(combos), args.poll_seconds, args.sync_seconds)

    workers: list[OkxWorker] = []
    threads: list[threading.Thread] = []
    for idx, (sym, iv) in enumerate(combos):
        w = OkxWorker(sym, iv, OkxFuturesClient(), store, engine,
                      poll_seconds=args.poll_seconds,
                      startup_delay=idx * (args.stagger_ms / 1000.0),
                      use_htf=not args.no_htf)
        workers.append(w)
        threads.append(threading.Thread(target=w.run, name=f"okx-{sym}-{iv}",
                                        daemon=True))

    stop_event = threading.Event()
    sync_thread = threading.Thread(
        target=_sync_loop, args=(engine, stop_event, args.sync_seconds), daemon=True)

    def shutdown(signum, frame):  # noqa: ARG001
        log.info("Kapatma — %d worker durduruluyor", len(workers))
        stop_event.set()
        for w in workers:
            w.stop()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for t in threads:
        t.start()
    sync_thread.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
