"""Binance Testnet canlı hat — (mainnet/testnet) veriyle tara, testnet'e emir at.

run_okx_demo'nun Binance karşılığı. Her (parite × TF) worker: veriyi çek →
scan_klines → setup AKTIF olunca BinanceTestEngine.open_trade (tek entry emri).
Ayrı thread periyodik sync() çalıştırır — çıkış engine-yönetimli (markPrice ile
SL/TP → MARKET reduceOnly; testnet native TP/SL'i reddediyor, -4120).

Kimlik ENV'den: BINANCE_API_KEY / BINANCE_SECRET (testnet.binancefuture.com).

VERİ: --data-base ile seç. Default mainnet fapi (temiz piyasa yapısı); VPS
coğrafi engelliyse --testnet-data ile testnet kendi verisine düş.
INSTRUMENT (tick/step/minNotional): DAİMA testnet'ten (emirler oraya gidiyor).

Düzeltme defaultları (OKX analizinden): risk $5 + notional tavanı KAPALI →
PaMonic'in dar-stop/yüksek-R kenarı tavana takılmaz.

Kullanım:
    BINANCE_API_KEY=... BINANCE_SECRET=... \\
    python -m terminal.cli.run_binance_test --combos-file config/tracked_combos.txt --pamonic
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
from terminal.data.binance_futures import (BINANCE_DATA_BASE, BinanceFuturesClient)
from terminal.data.binance_instruments import BinanceInstruments
from terminal.data.binance_trade import BINANCE_TESTNET, BinanceTestClient
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.lifecycle.states import TERMINAL_STATES
from terminal.lifecycle.tracker import LifecycleTracker
from terminal.paper.binance_engine import BinanceTestEngine
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


class BinanceWorker:
    """Bir (parite, TF) için Binance veri tarayıcı + testnet emir tetikleyici."""

    def __init__(self, symbol: str, interval: str, data: BinanceFuturesClient,
                 store: Store, engine: BinanceTestEngine, poll_seconds: int,
                 startup_delay: float, use_htf: bool, pamonic: bool = False) -> None:
        self.symbol = symbol
        self.interval = interval
        self.data = data
        self.store = store
        self.engine = engine
        self.poll_seconds = poll_seconds
        self.startup_delay = startup_delay
        self.use_htf = use_htf
        self.target_mode = "structural" if pamonic else "rr1"
        self._running = False
        self._tag = f"[BNB {symbol} {interval}]"
        self._klines: list[dict[str, Any]] = []

    def _on_transition(self, t) -> None:
        if t.new_state == "Aktif" and t.setup_id is not None:
            if t.setup.elenen:
                return
            self.engine.open_trade(t.setup, t.setup_id, t.trigger_time, klines=self._klines)
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
                self._klines = klines
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


def _sync_loop(engine: BinanceTestEngine, stop_event: threading.Event, interval: int) -> None:
    while not stop_event.is_set():
        try:
            n = engine.sync()
            if n:
                log.info("BNB SYNC: %d trade güncellendi | %s", n, engine.summary())
        except Exception as e:
            log.warning("BNB sync hatası: %s", e)
        stop_event.wait(interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-binance-test",
        description="Binance testnet canlı hat — veriyle tara, testnet'e emir")
    ap.add_argument("--combos-file", required=True)
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--stagger-ms", type=int, default=300)
    ap.add_argument("--sync-seconds", type=int, default=30)
    ap.add_argument("--risk", type=float, default=5.0,
                    help="İşlem başı sabit risk $ (default 5 — düşük risk PaMonic dar "
                         "stoplarını notional tavanına sığdırır).")
    ap.add_argument("--max-lever", type=int, default=50)
    ap.add_argument("--leverage", type=int, default=0, help="SABİT kaldıraç (0=agresif).")
    ap.add_argument("--max-notional", type=float, default=0.0,
                    help="Max pozisyon notional $ (0=SINIRSIZ — default). PaMonic kenarı "
                         "dar-stop/yüksek-R işlemlerde; tavan onları eler (OKX dersi).")
    ap.add_argument("--target-margin", type=float, default=30.0,
                    help="HEDEF margin $ (default 30) — kaldıracı notional'a göre seçer, "
                         "1K bakiyeye çok pozisyon. Risk yine sabit.")
    ap.add_argument("--max-open", type=int, default=0,
                    help="Aynı anda max açık pozisyon (0=sınırsız, boş USDT kapısı).")
    ap.add_argument("--min-free", type=float, default=0.0)
    ap.add_argument("--entry-type", choices=["market", "limit"], default="limit",
                    help="limit (DEFAULT — ideal harmonik fiyat) | market (anında dol).")
    ap.add_argument("--pamonic", action="store_true",
                    help="PaMonic: OB yoksa pas (enforce), dar OB stop + yapısal TP.")
    ap.add_argument("--data-base", default=BINANCE_DATA_BASE,
                    help=f"Market verisi tabanı (default {BINANCE_DATA_BASE}).")
    ap.add_argument("--testnet-data", action="store_true",
                    help="Market verisini de testnet'ten çek (VPS mainnet'e erişemiyorsa).")
    ap.add_argument("--no-htf", action="store_true")
    ap.add_argument("--no-telegram", action="store_true",
                    help="Telegram açılış/kapanış bildirimlerini kapat.")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    h_out = logging.StreamHandler(sys.stdout); h_out.setFormatter(fmt)
    h_out.addFilter(lambda rec: rec.levelno < logging.WARNING)
    h_err = logging.StreamHandler(sys.stderr); h_err.setFormatter(fmt)
    h_err.setLevel(logging.WARNING)
    root = logging.getLogger(); root.setLevel(args.log_level.upper())
    root.handlers[:] = [h_out, h_err]
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    data_base = BINANCE_TESTNET if args.testnet_data else args.data_base
    combos = _load_combos(Path(args.combos_file))
    if not combos:
        print("HATA: combos boş.", file=sys.stderr)
        return 1

    trade_client = BinanceTestClient()
    if not trade_client.has_credentials():
        print("HATA: BINANCE_API_KEY / BINANCE_SECRET env gerekli.", file=sys.stderr)
        return 1
    if not trade_client.ping_auth():
        print("HATA: Binance testnet kimlik doğrulanamadı (anahtar/secret?).", file=sys.stderr)
        return 1
    trade_client.set_one_way_mode()
    log.info("Binance testnet bağlantı OK — bakiye: %s USDT | veri: %s",
             trade_client.equity(), data_base)

    Store().close()
    store = Store()
    # INSTRUMENT: emirler testnet'e gidiyor → tick/step/minNotional testnet'ten
    instruments = BinanceInstruments(base_url=BINANCE_TESTNET, max_lever=args.max_lever)
    # GERÇEK kaldıraç bracket'leri (per-sembol max kaldıraç + notional cap) → -4028/
    # -2027 önler, düşük-max-kaldıraçlı junk semboller min_lever kapısıyla elenir.
    try:
        n = instruments.apply_brackets(trade_client.leverage_brackets())
        log.info("Kaldıraç bracket'leri uygulandı (%d sembol)", n)
    except Exception as e:
        log.warning("Kaldıraç bracket'leri çekilemedi (default max_lever kullanılacak): %s", e)

    before = len(combos)
    combos = [(s, iv) for s, iv in combos if instruments.get(s) is not None]
    skipped = before - len(combos)
    if skipped:
        log.info("Binance testnet'te olmayan %d kombinasyon elendi (%d → %d)",
                 skipped, before, len(combos))
    if not combos:
        print("HATA: Binance testnet'te işlem gören parite kalmadı.", file=sys.stderr)
        return 1

    tg = None
    if not args.no_telegram:
        try:
            from terminal.telegram_bot.client import TelegramClient, TelegramError
            try:
                tg = TelegramClient()
                log.info("Telegram bildirimleri AKTİF (açılış/kapanış)")
            except TelegramError as e:
                log.info("Telegram kapalı (token yok): %s", e)
        except Exception as e:
            log.warning("Telegram client yüklenemedi: %s", e)

    engine = BinanceTestEngine(store, trade_client, instruments,
                               risk_per_trade=args.risk, max_lever=args.max_lever,
                               pamonic=args.pamonic, max_open=args.max_open,
                               fixed_leverage=args.leverage, max_notional=args.max_notional,
                               target_margin=args.target_margin, min_free_usdt=args.min_free,
                               entry_type=args.entry_type, tg=tg)

    log.info("Binance hat: %d kombinasyon, poll %ds, sync %ds, PaMonic=%s, risk $%s, "
             "max-notional %s", len(combos), args.poll_seconds, args.sync_seconds,
             args.pamonic, args.risk, args.max_notional or "∞")

    workers: list[BinanceWorker] = []
    threads: list[threading.Thread] = []
    for idx, (sym, iv) in enumerate(combos):
        w = BinanceWorker(sym, iv, BinanceFuturesClient(base_url=data_base), store, engine,
                          poll_seconds=args.poll_seconds,
                          startup_delay=idx * (args.stagger_ms / 1000.0),
                          use_htf=not args.no_htf, pamonic=args.pamonic)
        workers.append(w)
        threads.append(threading.Thread(target=w.run, name=f"bnb-{sym}-{iv}", daemon=True))

    stop_event = threading.Event()
    sync_thread = threading.Thread(target=_sync_loop,
                                   args=(engine, stop_event, args.sync_seconds), daemon=True)

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
