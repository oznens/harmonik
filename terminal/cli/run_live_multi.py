"""Faz 8: Çok parite × çok TF eşzamanlı canlı tarama.

Her (parite, aralık) kombinasyonu kendi thread'inde çalışır:
KlinePoller → scan → lifecycle → Telegram. SQLite WAL modu sayesinde
paralel yazımlar serileşerek çalışır.

Kullanım:
    python -m terminal.cli.run_live_multi --symbols BTCUSDT,ETHUSDT,... --intervals 15m,60m,4h
    python -m terminal.cli.run_live_multi --symbols-file pairs.txt --intervals 60m,4h
"""
from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from terminal.cli.run_data import _normalize_interval
from terminal.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from terminal.data.kline_poller import KlinePoller
from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.lifecycle.states import ADAY, AKTIF, EO, STOP, TP, ZI
from terminal.lifecycle.tracker import LifecycleTracker, Transition
from terminal.quality.htf_ltf import htf_for
from terminal.telegram_bot.cards import aday_card, aktif_card, exit_card
from terminal.telegram_bot.charts import render_setup_chart
from terminal.telegram_bot.client import TelegramClient, TelegramError

log = logging.getLogger(__name__)


def _fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


class PairWorker:
    """Bir (symbol, interval) için kendi thread'inde çalışan canlı tarayıcı."""

    FRESH_ADAY_BARS = 3

    def __init__(
        self,
        symbol: str,
        interval: str,
        tg: TelegramClient | None,
        min_q: int,
        include_elenen: bool,
        no_chart: bool,
        use_htf: bool,
        zigzag_threshold: float | None,
        startup_delay: float = 0.0,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.tg = tg
        self.min_q = min_q
        self.include_elenen = include_elenen
        self.no_chart = no_chart
        self.use_htf = use_htf
        self.threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
        self.htf_interval = htf_for(interval) if use_htf else None
        self.startup_delay = startup_delay

        # Thread-local kaynaklar (run() içinde yaratılır)
        self.client: MexcClient | None = None
        self.store: Store | None = None
        self.poller: KlinePoller | None = None
        self.tracker: LifecycleTracker | None = None
        self._running = False
        self._htf_cache: list[dict[str, Any]] | None = None
        self._tag = f"[{symbol} {interval}]"

    def _on_transition(self, t: Transition) -> None:
        if self.tg is None:
            return
        if t.new_state == ADAY:
            if t.setup.elenen and not self.include_elenen:
                return
            if t.setup.q_score and t.setup.q_score < self.min_q:
                return
            latest = self.poller.buffer.latest if self.poller else None
            if latest is not None:
                age = (latest["open_time"] - t.setup.pivots["D"].time) // self.tracker._interval_ms()
                if age > self.FRESH_ADAY_BARS:
                    return
        try:
            if t.new_state == ADAY:
                karakter = self.store.get_karakter_score(
                    t.setup.symbol, t.setup.interval, t.setup.pattern_name, t.setup.direction,
                )
                caption = aday_card(t.setup, karakter=karakter)
                if not self.no_chart:
                    chart = render_setup_chart(t.setup, self.poller.buffer.as_list())
                    self.tg.send_photo(chart, caption=caption)
                else:
                    self.tg.send_message(caption)
            elif t.new_state == AKTIF:
                self.tg.send_message(aktif_card(t.setup, t.trigger_price or t.setup.entry, t.trigger_time))
            elif t.new_state in (TP, STOP, ZI, EO):
                self.tg.send_message(exit_card(t.setup, t.new_state, t.trigger_price or t.setup.entry, t.trigger_time))
        except TelegramError as e:
            log.warning("%s Telegram: %s", self._tag, e)

    def _fetch_htf(self) -> list[dict[str, Any]] | None:
        if self.htf_interval is None or self.client is None:
            return None
        try:
            self._htf_cache = self.client.klines(self.symbol, self.htf_interval, limit=120)
        except MexcError as e:
            log.warning("%s HTF fetch: %s", self._tag, e)
        return self._htf_cache

    def _process(self, _closed: dict[str, Any] | None) -> None:
        klines = self.poller.buffer.as_list()
        if len(klines) < 20:
            return
        htf_klines = self._fetch_htf()
        setups = scan_klines(klines, self.symbol, self.interval,
                             zigzag_threshold=self.threshold, htf_klines=htf_klines)
        for s in setups:
            sid = self.store.upsert_setup(s)
            if self.store.get_lifecycle(sid) is None:
                d_time = s.pivots["D"].time
                tag = "YENI" if d_time >= klines[-3]["open_time"] else "TARIHSEL"
                log.info("%s [%s] %s | id=%d", self._tag, tag, s.summary(), sid)
                self.tracker.register_new(s, sid)
        self.tracker.advance(klines)

    def run(self) -> None:
        # Stagger startup → MEXC rate limit'i tampona al
        if self.startup_delay > 0:
            time.sleep(self.startup_delay)
        log.info("%s başlıyor (ZigZag %.4f)", self._tag, self.threshold)
        self.client = MexcClient()
        self.store = Store()
        self.tracker = LifecycleTracker(
            self.symbol, self.interval, self.store, on_transition=self._on_transition,
        )
        self.poller = KlinePoller(
            self.symbol, self.interval, self.client, self.store, on_closed=self._process,
        )
        try:
            self.poller.bootstrap()
            self._process(None)
            self._running = True
            self.poller.poll_loop()
        except Exception:
            log.exception("%s worker hatası", self._tag)
        finally:
            try:
                self.client.close()
            except Exception:
                pass
            try:
                self.store.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        if self.poller is not None:
            self.poller.stop()


def _load_symbols(args) -> list[str]:
    if args.symbols_file:
        p = Path(args.symbols_file)
        if not p.exists():
            raise SystemExit(f"Dosya yok: {p}")
        raw = p.read_text(encoding="utf-8").splitlines()
        items = [line.strip().upper() for line in raw
                 if line.strip() and not line.strip().startswith("#")]
    elif args.symbols:
        items = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        raise SystemExit("--symbols veya --symbols-file gerekli")
    if not items:
        raise SystemExit("Parite listesi boş")
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-live-multi",
        description="terminalMiraz — Faz 8 (çok parite × çok TF eşzamanlı canlı tarama)",
    )
    parser.add_argument("--symbols", help="Virgülle ayrılmış pariteler")
    parser.add_argument("--symbols-file", help="Her satırda bir parite olan dosya (# yorum)")
    parser.add_argument("--intervals", required=True,
                        help="Virgülle ayrılmış aralıklar (örn. 15m,30m,60m,4h)")
    parser.add_argument("--zigzag", type=float, default=None)
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-chart", action="store_true")
    parser.add_argument("--min-q", type=int, default=0)
    parser.add_argument("--include-elenen", action="store_true")
    parser.add_argument("--no-htf", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--stagger-ms", type=int, default=200,
                        help="Her worker arasında bekleme (ms). Bootstrap rate limit'i tampona alır.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    symbols = _load_symbols(args)
    intervals = [_normalize_interval(i) for i in args.intervals.split(",") if i.strip()]
    combos = [(s, i) for s in symbols for i in intervals]

    log.info("Toplam %d kombinasyon: %d parite × %d TF",
             len(combos), len(symbols), len(intervals))

    # Migration için tek bir Store başlat ve kapat (schema kurulumu)
    Store().close()

    # Telegram (paylaşımlı)
    tg: TelegramClient | None = None
    if not args.no_telegram:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                tg = TelegramClient()
                me = tg.get_me()
                log.info("Telegram bağlı: @%s", me["username"])
            except TelegramError as e:
                log.warning("Telegram bağlanamadı: %s", e)
                tg = None
        else:
            log.warning("Telegram env eksik → bildirim KAPALI")

    workers: list[PairWorker] = []
    threads: list[threading.Thread] = []

    for idx, (sym, iv) in enumerate(combos):
        w = PairWorker(
            symbol=sym, interval=iv, tg=tg,
            min_q=args.min_q, include_elenen=args.include_elenen,
            no_chart=args.no_chart, use_htf=not args.no_htf,
            zigzag_threshold=args.zigzag,
            startup_delay=idx * (args.stagger_ms / 1000.0),
        )
        workers.append(w)
        t = threading.Thread(target=w.run, name=f"worker-{sym}-{iv}", daemon=True)
        threads.append(t)

    shutdown_event = threading.Event()

    def shutdown(signum, frame):  # noqa: ARG001
        log.info("Kapatma sinyali, %d worker durduruluyor...", len(workers))
        shutdown_event.set()
        for w in workers:
            w.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for t in threads:
        t.start()

    try:
        # Ana thread: shutdown sinyalini bekle
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)
            # Hangi worker'lar yaşıyor?
            alive = sum(1 for t in threads if t.is_alive())
            if alive == 0:
                log.warning("Tüm worker'lar durdu, çıkılıyor")
                break
    finally:
        log.info("Worker'lar bitiriliyor (max 15s bekle)...")
        for t in threads:
            t.join(timeout=15)
        if tg is not None:
            tg.close()
        log.info("Temiz kapanış. %d worker tamamlandı.", len(workers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
