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
from terminal.lifecycle.states import TERMINAL_STATES
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
                 startup_delay: float, use_htf: bool, pamonic: bool = False) -> None:
        self.symbol = symbol
        self.interval = interval
        self.data = data
        self.store = store
        self.engine = engine
        self.poll_seconds = poll_seconds
        self.startup_delay = startup_delay
        self.use_htf = use_htf
        # PaMonic modunda yapısal TP (tp2=A) lazım → structural tara; yoksa rr1.
        self.target_mode = "structural" if pamonic else "rr1"
        self._running = False
        self._tag = f"[OKX {symbol} {interval}]"
        self._last_open: int | None = None
        self._klines: list[dict[str, Any]] = []   # son tarama mumları (PaMonic OB için)

    def _on_transition(self, t) -> None:
        # AKTIF geçişinde demo emri at (paper'ın limit moduna benzer)
        if t.new_state == "Aktif" and t.setup_id is not None:
            if t.setup.elenen:
                return
            self.engine.open_trade(t.setup, t.setup_id, t.trigger_time,
                                   klines=self._klines)
        # Setup terminal'e (TP/STOP/ZI/EO) geçti: limit emrimiz DOLMADIYSA artık
        # geçersiz (hareket bizsiz oldu) → iptal et, margin+parite serbest kalsın.
        elif t.new_state in TERMINAL_STATES and t.setup_id is not None:
            self.engine.cancel_if_unfilled(t.setup_id)

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
                self._klines = klines   # PaMonic OB tespiti için sakla
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
                                         target_mode=self.target_mode, include_abcd=True)
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
    ap.add_argument("--leverage", type=int, default=0,
                    help="SABİT kaldıraç (örn 20). 0=agresif (paritenin max'ı). "
                         "Cross margin; risk yine $20 sabit, kaldıraç teminatı belirler.")
    ap.add_argument("--max-notional", type=float, default=3000.0,
                    help="Max pozisyon notional $ (0=sınırsız). PaMonic dar stop "
                         "notional'ı şişirir → bunu aşan setup atlanır (51008 önler).")
    ap.add_argument("--target-margin", type=float, default=0.0,
                    help="HEDEF margin $ (örn 30). Kaldıracı notional'a göre seçer ki "
                         "her işlem ~bu kadar teminat tutsun → 1K bakiyeye çok poz. "
                         "Risk yine $20 sabit. 0=kapalı (leverage/agresif kullan).")
    ap.add_argument("--max-open", type=int, default=0,
                    help="Aynı anda max açık pozisyon (0=sınırsız). 0 ise sınır "
                         "boş USDT'dir: her açılışta canlı availBal kapısı → bakiye "
                         "oldukça açar, bitince durur (51008 önlenir).")
    ap.add_argument("--min-free", type=float, default=0.0,
                    help="İşlem sonrası boşta tutulacak min USDT tamponu (0=tümünü "
                         "kullan). Boş USDT < margin+tampon ise açma.")
    ap.add_argument("--entry-type", choices=["market", "limit"], default="limit",
                    help="limit (DEFAULT — sadece fiyat D seviyesine gelirse gir, "
                         "ideal harmonik fiyat; market kovalama -661 USD/WR43 ettirdi) | "
                         "market (setup AKTIF olunca canlı fiyattan anında dol).")
    ap.add_argument("--pamonic", action="store_true",
                    help="PaMonic modu: OB yoksa pas geç (enforce), OB varsa dar "
                         "stop (OB arkası) + yapısal TP. OB filtreli A/B testi.")
    ap.add_argument("--no-htf", action="store_true")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    # INFO/DEBUG → stdout (okx.log), WARNING+ → stderr (okx.err). Böylece .err
    # sadece GERÇEK sorunları (ret/çökme) tutar, normal akış .log'a gider.
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    h_out = logging.StreamHandler(sys.stdout)
    h_out.setFormatter(fmt)
    h_out.addFilter(lambda rec: rec.levelno < logging.WARNING)   # sadece <WARNING
    h_err = logging.StreamHandler(sys.stderr)
    h_err.setFormatter(fmt)
    h_err.setLevel(logging.WARNING)                              # WARNING ve üstü
    root = logging.getLogger()
    root.setLevel(args.log_level.upper())
    root.handlers[:] = [h_out, h_err]
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

    # OKX'te SWAP olmayan pariteleri ele (MEXC combos'unda olup OKX'te olmayanlar
    # 51001 verir + boş worker RAM yer). Başta tek instruments çağrısıyla filtrele.
    before = len(combos)
    combos = [(s, iv) for s, iv in combos if instruments.get(s) is not None]
    skipped = before - len(combos)
    if skipped:
        log.info("OKX'te olmayan %d kombinasyon elendi (%d → %d)",
                 skipped, before, len(combos))
    if not combos:
        print("HATA: OKX'te işlem gören parite kalmadı.", file=sys.stderr)
        return 1

    engine = OkxDemoEngine(store, trade_client, instruments,
                           risk_per_trade=args.risk, max_lever=args.max_lever,
                           pamonic=args.pamonic, max_open=args.max_open,
                           fixed_leverage=args.leverage, max_notional=args.max_notional,
                           target_margin=args.target_margin, min_free_usdt=args.min_free,
                           entry_type=args.entry_type)

    log.info("OKX hat: %d kombinasyon, poll %ds, sync %ds, PaMonic=%s",
             len(combos), args.poll_seconds, args.sync_seconds, args.pamonic)

    workers: list[OkxWorker] = []
    threads: list[threading.Thread] = []
    for idx, (sym, iv) in enumerate(combos):
        w = OkxWorker(sym, iv, OkxFuturesClient(), store, engine,
                      poll_seconds=args.poll_seconds,
                      startup_delay=idx * (args.stagger_ms / 1000.0),
                      use_htf=not args.no_htf, pamonic=args.pamonic)
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
