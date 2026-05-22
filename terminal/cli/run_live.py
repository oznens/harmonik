"""Faz 3: canlı veri + formasyon tespit + yaşam döngüsü + Telegram bildirim.

Akış:
  1. KlinePoller her yeni kapanan mumda on_closed callback'i çağırır.
  2. Callback:
     a) scan_klines ile formasyon arar; yeni Aday setup'ları DB'ye yazar, lifecycle.register_new'a iletir.
     b) lifecycle.advance ile açık (Aday/Aktif) setup'ları ilerletir.
     c) Geçiş varsa Telegram'a kart + chart gönderir.

Kullanım:
    python -m terminal.cli.run_live --symbol BTCUSDT --interval 1h
    python -m terminal.cli.run_live --symbol AVAXUSDT --interval 60m --no-telegram
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
from datetime import datetime, timezone
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-live",
        description="terminalMiraz — Faz 3 (canlı veri + tespit + lifecycle + Telegram)",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--zigzag", type=float, default=None)
    parser.add_argument("--no-telegram", action="store_true",
                        help="Telegram bildirimleri kapat (sadece DB)")
    parser.add_argument("--no-chart", action="store_true",
                        help="Chart oluşturma; sadece metin gönder")
    parser.add_argument("--min-q", type=int, default=0,
                        help="Bu Q skorunun altındakileri Telegram'a yollama (varsayılan 0)")
    parser.add_argument("--include-elenen", action="store_true",
                        help="Elenen setup'ları da Telegram'a yolla (varsayılan: hayır)")
    parser.add_argument("--no-htf", action="store_true",
                        help="HTF/LTF kontrolünü atla (Q skorunda HTF puanı 0)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbol = args.symbol.upper().strip()
    interval = _normalize_interval(args.interval)
    threshold = args.zigzag if args.zigzag is not None else default_threshold(interval)

    # Telegram kurulumu (varsa)
    tg: TelegramClient | None = None
    if not args.no_telegram:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            log.warning("Telegram konfigürasyonu eksik (.env'de TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID gerekli). "
                        "Bildirim KAPALI. (--no-telegram ile sustur.)")
        else:
            try:
                tg = TelegramClient()
                me = tg.get_me()
                log.info("Telegram bağlandı: @%s", me["username"])
            except TelegramError as e:
                log.warning("Telegram bağlantısı başarısız: %s — bildirim KAPALI", e)
                tg = None

    client = MexcClient()
    store = Store()
    if not client.ping():
        log.error("MEXC ping başarısız.")
        return 1

    # Stale Aday spam'ini önlemek için: D pivot'u son N mumdan eski olan
    # Aday'lar Telegram'a gitmez (sadece DB'ye). Aktif/TP/STOP/ZI/EO her zaman gider.
    FRESH_ADAY_BARS = 3

    def on_transition(t: Transition) -> None:
        if tg is None:
            return
        # Elenen ve düşük-Q filtreleri (Aday için geçerli; Aktif sonrası bilgi her zaman gider)
        if t.new_state == ADAY:
            if t.setup.elenen and not args.include_elenen:
                log.debug("Aday elenen, Telegram'a gitmiyor")
                return
            if t.setup.q_score and t.setup.q_score < args.min_q:
                log.debug("Aday Q=%d < %d, Telegram'a gitmiyor", t.setup.q_score, args.min_q)
                return
            # Aday tazeliği kontrolü
            latest_bar = poller.buffer.latest
            if latest_bar is not None:
                interval_ms = tracker._interval_ms()
                age_bars = (latest_bar["open_time"] - t.setup.pivots["D"].time) // interval_ms
                if age_bars > FRESH_ADAY_BARS:
                    log.debug("Aday eski (%d mum), Telegram'a gitmiyor", age_bars)
                    return
        try:
            if t.new_state == ADAY:
                # Karakter skoru lookup (varsa karta yansıt)
                karakter = store.get_karakter_score(
                    t.setup.symbol, t.setup.interval, t.setup.pattern_name, t.setup.direction,
                )
                caption = aday_card(t.setup, karakter=karakter)
                if not args.no_chart:
                    chart = render_setup_chart(t.setup, poller.buffer.as_list())
                    tg.send_photo(chart, caption=caption)
                else:
                    tg.send_message(caption)
            elif t.new_state == AKTIF:
                tg.send_message(aktif_card(t.setup, t.trigger_price or t.setup.entry, t.trigger_time))
            elif t.new_state in (TP, STOP, ZI, EO):
                tg.send_message(exit_card(t.setup, t.new_state, t.trigger_price or t.setup.entry, t.trigger_time))
        except TelegramError as e:
            log.warning("Telegram gönderim hatası: %s", e)

    tracker = LifecycleTracker(symbol, interval, store, on_transition=on_transition)

    # HTF veri çekme: aynı HTF aralığı içinde tekrar tekrar çağırma — kısa cache.
    htf_interval = htf_for(interval) if not args.no_htf else None
    htf_cache: dict[str, list[dict[str, Any]]] = {}

    def fetch_htf_klines() -> list[dict[str, Any]] | None:
        if htf_interval is None:
            return None
        try:
            ks = client.klines(symbol, htf_interval, limit=120)
            htf_cache[htf_interval] = ks
            return ks
        except MexcError as e:
            log.warning("HTF (%s) klines alınamadı: %s — eski cache kullanılıyor", htf_interval, e)
            return htf_cache.get(htf_interval)

    def process_new_candle(_closed: dict[str, Any] | None) -> None:
        klines = poller.buffer.as_list()
        if len(klines) < 20:
            return

        htf_klines = fetch_htf_klines()

        # 1) Formasyon tara (Q + HTF entegrasyonlu)
        setups = scan_klines(klines, symbol, interval,
                             zigzag_threshold=threshold,
                             htf_klines=htf_klines)
        for s in setups:
            setup_id = store.upsert_setup(s)
            if store.get_lifecycle(setup_id) is None:
                d_time = s.pivots["D"].time
                tag = "YENI" if d_time >= klines[-3]["open_time"] else "TARIHSEL"
                log.info("[%s] tespit: %s | D@%s | id=%d",
                         tag, s.summary(), _fmt(d_time), setup_id)
                tracker.register_new(s, setup_id)

        # 2) Açık setup'ları ilerlet
        transitions = tracker.advance(klines)
        if transitions:
            log.info("Lifecycle geçişleri: %d", len(transitions))

    poller = KlinePoller(symbol, interval, client, store, on_closed=process_new_candle)

    def shutdown(signum, frame):  # noqa: ARG001
        log.info("Kapatma sinyali alındı...")
        poller.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        poller.bootstrap()
        log.info("İlk tarama (ZigZag eşik=%.4f)...", threshold)
        process_new_candle(None)
        stats = store.lifecycle_stats(symbol, interval)
        log.info("Lifecycle dağılımı (%s %s): %s", symbol, interval, stats)
        log.info("Canlı polling başlıyor...")
        poller.poll_loop()
    finally:
        client.close()
        if tg is not None:
            tg.close()
        stats = store.lifecycle_stats(symbol, interval)
        store.close()
        log.info("Temiz kapanış. Lifecycle dağılımı: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
