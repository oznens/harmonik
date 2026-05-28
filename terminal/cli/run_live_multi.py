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
from pathlib import Path
from typing import Any

from terminal.cli.run_data import _normalize_interval
from terminal.config import POLL_INTERVAL_SECONDS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from terminal.data.kline_poller import KlinePoller
from terminal.data.mexc_client import MexcClient, MexcError
from terminal.data.mexc_futures import MexcFuturesClient, MexcFuturesError
from terminal.paper.engine import PaperEngine
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.lifecycle.states import ADAY, AKTIF, EO, STOP, TP, ZI
from terminal.lifecycle.tracker import LifecycleTracker, Transition
from terminal.quality.htf_ltf import htf_for
from terminal.telegram_bot.cards import aday_card, aktif_card, exit_card
from terminal.telegram_bot.charts import render_setup_chart
from terminal.telegram_bot.client import TelegramClient, TelegramError
from terminal.timeutil import format_local

log = logging.getLogger(__name__)

# Potansiyel (henüz oluşmamış) pattern bildirimleri SADECE bu TF'lerde Telegram'a
# gider — kısa vadeli TF gürültüsünü kapatır. DB'ye (UI) tüm TF'ler yazılır.
POTENTIAL_TG_INTERVALS = {"4h", "1d"}

# HTF verisi yavaş değişir → bu süreden sık yeniden çekme (rate-limit tasarrufu).
HTF_REFRESH_SECONDS = 120


def _fmt(ms: int) -> str:
    return format_local(ms)


class PairWorker:
    """Bir (symbol, interval) için kendi thread'inde çalışan canlı tarayıcı."""

    FRESH_ADAY_BARS = 3

    def __init__(
        self,
        symbol: str,
        interval: str,
        tg: TelegramClient | None,
        min_q: int,
        min_karakter: float,
        min_confluence: int,
        include_elenen: bool,
        no_chart: bool,
        no_potential: bool,
        use_htf: bool,
        zigzag_threshold: float | None,
        use_futures: bool = False,
        paper_engine: "PaperEngine | None" = None,
        startup_delay: float = 0.0,
        poll_seconds: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.tg = tg
        self.min_q = min_q
        self.min_confluence = min_confluence
        self.min_karakter = min_karakter
        self.include_elenen = include_elenen
        self.no_chart = no_chart
        self.no_potential = no_potential
        self.use_futures = use_futures
        self.paper = paper_engine
        self.use_htf = use_htf
        self.threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
        self.htf_interval = htf_for(interval) if use_htf else None
        self.startup_delay = startup_delay
        self.poll_seconds = poll_seconds

        # Thread-local kaynaklar (run() içinde yaratılır)
        self.client: MexcClient | None = None
        self.store: Store | None = None
        self.poller: KlinePoller | None = None
        self.tracker: LifecycleTracker | None = None
        self._running = False
        self._htf_cache: list[dict[str, Any]] | None = None
        self._htf_last_fetch = 0.0  # HTF cache zaman damgası (zaman-cache için)
        self._tag = f"[{symbol} {interval}]"
        # Potansiyel pattern dedup key — (spec_name, x_time, a_time, b_time, c_time)
        self._last_potential_key: tuple | None = None
        # Gerçekçi giriş: AKTIF olan setup'lar sonraki barın açılışından
        # doldurulmak üzere burada bekler — {setup_id: Setup}.
        self._pending_entries: dict[int, Any] = {}
        # Bootstrap reconcile sırasında True → kaçan çıkışlar paper'a yansır ama
        # Telegram'a eski bildirim yağmuru gönderilmez.
        self._in_reconcile = False

    def _on_transition(self, t: Transition) -> None:
        # Giriş geçişleri (ADAY/AKTIF) için freshness + elenen kapısı: bootstrap'ta
        # bulunan TARIHSEL setupları (eski D pivot) ne paper'a aç ne bildir.
        # register_new agresif girişte AKTIF'i bootstrap'ta da emit ettiği için
        # bu kapı paper'ın eski setuplarla dolmasını engeller. Çıkışlar (TP/STOP/
        # ZI/EO) muaf — gerçek zamanlı kapanışlar her zaman işlenir.
        if t.new_state in (ADAY, AKTIF):
            if t.setup.elenen and not self.include_elenen:
                log.info("%s [%s] %s elenen → atla",
                         self._tag, t.new_state, t.setup.pattern_name)
                return
            latest = self.poller.buffer.latest if self.poller else None
            if latest is not None and self.tracker is not None:
                age = (latest["open_time"] - t.setup.pivots["D"].time) // self.tracker._interval_ms()
                if age > self.FRESH_ADAY_BARS:
                    log.info("%s [%s] %s D pivot eski (%d bar) → atla",
                             self._tag, t.new_state, t.setup.pattern_name, age)
                    return

        # Paper trade motoru — confluence/Q filtrelerinden bağımsız.
        # AKTIF: hemen açma — gerçekçi giriş için SONRAKİ barın açılışından
        # doldurulmak üzere pending'e al (fill + bildirim _fill_pending_entries
        # içinde). Çıkış: paper'da kapat.
        paper_closed = None  # bu çıkışta gerçekten bir paper pozisyonu kapandı mı
        if self.paper is not None and t.setup_id is not None:
            if t.new_state == AKTIF:
                self._pending_entries[t.setup_id] = t.setup
                return  # dolum sonraki barda; AKTIF kartı/bildirimi o an
            elif t.new_state in (TP, STOP, ZI, EO):
                paper_closed = self.paper.close_trade(
                    t.setup_id, t.new_state,
                    t.trigger_price or t.setup.entry, t.trigger_time,
                )

        # Reconcile catch-up: paper senkronlandı, geçmiş çıkışları Telegram'a
        # yağdırma (deploy/restart sonrası bildirim seli olmasın).
        if self._in_reconcile:
            return

        if self.tg is None:
            return

        # Telegram noise filtreleri (Q/confluence/karakter) — yalnızca kart
        # bildirimlerini etkiler (paper modu kapalıyken AKTIF kartı + ADAY kartı).
        if t.new_state in (ADAY, AKTIF):
            if t.setup.q_score and t.setup.q_score < self.min_q:
                log.info("%s [%s] %s Q=%d < min_q=%d → filtre dışı",
                         self._tag, t.new_state, t.setup.pattern_name,
                         t.setup.q_score, self.min_q)
                return
            if self.min_confluence > 0 and t.setup.confluence_score < self.min_confluence:
                log.info("%s [%s] %s confluence=%d < min=%d → filtre dışı",
                         self._tag, t.new_state, t.setup.pattern_name,
                         t.setup.confluence_score, self.min_confluence)
                return
            # Karakter skoru filtresi: backtest verisi varsa ve düşükse Telegram'a gitme
            if self.min_karakter > 0 and self.store is not None:
                kar = self.store.get_karakter_score(
                    t.setup.symbol, t.setup.interval, t.setup.pattern_name, t.setup.direction,
                )
                if kar is not None and kar[1] >= 2 and kar[0] < self.min_karakter:
                    log.info("%s [%s] karakter %.1f < %.1f → filtre dışı",
                             self._tag, t.new_state, kar[0], self.min_karakter)
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
                karakter = self.store.get_karakter_score(
                    t.setup.symbol, t.setup.interval, t.setup.pattern_name, t.setup.direction,
                )
                caption = aday_card(t.setup, karakter=karakter)
                # Paper bilgisi varsa ekle
                if self.paper is not None and t.setup_id is not None:
                    eq = self.paper.get_equity()
                    caption += f"\n\n💰 Paper: equity ${eq:.2f}"
                if not self.no_chart:
                    chart = render_setup_chart(t.setup, self.poller.buffer.as_list())
                    self.tg.send_photo(chart, caption=caption)
                else:
                    self.tg.send_message(caption)
                log.info("%s [AKTIF] %s %s conf=%d Q=%d → Telegram yollandı",
                         self._tag, t.setup.pattern_name, t.setup.direction,
                         t.setup.confluence_score, t.setup.q_score or 0)
            elif t.new_state in (TP, STOP, ZI, EO):
                # Paper modunda SADECE gerçekten paper pozisyonu kapanan coinleri
                # bildir (Telegram = dashboard). Paper kapalıysa tüm çıkışlar.
                if self.paper is not None and paper_closed is None:
                    return
                msg = exit_card(t.setup, t.new_state,
                                t.trigger_price or t.setup.entry, t.trigger_time)
                if self.paper is not None:
                    summary = self.paper.summary()
                    msg += (f"\n\n💰 Paper: equity ${summary['current_equity']:.2f} "
                            f"({summary['pnl_pct']:+.1f}%) | {summary['total_trades']} trade "
                            f"WR {summary['win_rate']:.1f}%")
                self.tg.send_message(msg)
        except TelegramError as e:
            log.warning("%s Telegram hatasi (%s): %s",
                        self._tag, t.new_state, e)
        except Exception as e:
            log.exception("%s _on_transition beklenmedik hata: %s", self._tag, e)

    def _notify_trade_opened(self, setup, trade) -> None:
        """Paper pozisyon açıldığında Telegram bildirimi (filtrelerden bağımsız).

        Confluence/Q eşiklerine takılsa bile, sistem gerçekten paper işlem
        açtıysa kullanıcı haberdar edilir. Çift mesaj olmaması için AKTIF kartı
        yerine bu zengin "İŞLEM AÇILDI" kartı gönderilir.
        """
        try:
            karakter = None
            if self.store is not None:
                karakter = self.store.get_karakter_score(
                    setup.symbol, setup.interval, setup.pattern_name, setup.direction,
                )
            eq = self.paper.get_equity()
            caption = aday_card(setup, karakter=karakter)
            # Gerçek dolum (sonraki bar açılışı) ideal D'den sapmış olabilir
            slip = ((trade.entry_price - setup.entry) / setup.entry * 100
                    if setup.entry else 0.0)
            caption += (
                "\n\n📈 *İŞLEM AÇILDI* (paper)\n"
                f"Dolum: `{trade.entry_price:.6g}` (sonraki bar açılışı, "
                f"ideal `{setup.entry:.6g}` · {slip:+.2f}%)\n"
                f"Pozisyon: `${trade.position_usd:.0f}`  ·  "
                f"Kaldıraç: `{trade.leverage:.0f}x`  ·  Risk: `${trade.risk_usd:.0f}`\n"
                f"Equity: `${eq:.2f}`"
            )
            if not self.no_chart:
                chart = render_setup_chart(setup, self.poller.buffer.as_list())
                self.tg.send_photo(chart, caption=caption)
            else:
                self.tg.send_message(caption)
            log.info("%s [İŞLEM AÇILDI] %s %s pos=$%.0f lev=%.0fx conf=%d → Telegram",
                     self._tag, setup.pattern_name, setup.direction,
                     trade.position_usd, trade.leverage, setup.confluence_score)
        except TelegramError as e:
            log.warning("%s işlem-açıldı Telegram hatası: %s", self._tag, e)
        except Exception as e:
            log.exception("%s _notify_trade_opened hata: %s", self._tag, e)

    def _fetch_htf(self) -> list[dict[str, Any]] | None:
        if self.htf_interval is None or self.client is None:
            return None
        # HTF verisi yavaş değişir; her bar değil en fazla HTF_REFRESH_SECONDS'ta
        # bir çek → 250 kombinasyonda istek yükünü ciddi azaltır (rate-limit).
        now = time.time()
        if self._htf_cache is not None and (now - self._htf_last_fetch) < HTF_REFRESH_SECONDS:
            return self._htf_cache
        try:
            self._htf_cache = self.client.klines(self.symbol, self.htf_interval, limit=120)
            self._htf_last_fetch = now
        except (MexcError, MexcFuturesError) as e:
            log.warning("%s HTF fetch: %s", self._tag, e)  # eski cache'i koru
        return self._htf_cache

    def _fill_pending_entries(self, fill_bar: dict[str, Any]) -> None:
        """Önceki barda AKTIF olan setup'ları bu barın AÇILIŞINDAN doldur.

        Gerçekçi market girişi: oluşum bar kapanışında onaylandı → emir bir
        SONRAKİ barın açılış fiyatından dolar. fill_bar = yeni kapanan bar
        (klines[-1]); P&L bu fiyata göre hesaplanır. _process başında, tarama
        ve advance'ten ÖNCE çağrılır (aynı bar içinde açılıp kapanabilsin).
        """
        if not self._pending_entries or self.paper is None:
            return
        fill_price = fill_bar["open"]
        fill_time = fill_bar["open_time"]
        pending = self._pending_entries
        self._pending_entries = {}
        for sid, setup in pending.items():
            # Setup dolum beklerken zaten kapandıysa (backfill/advance terminal
            # yaptıysa) işlemi açma — stale trade olmasın.
            life = self.store.get_lifecycle(sid) if self.store else None
            if life is None or life["state"] != AKTIF:
                continue
            trade = self.paper.open_trade(setup, sid, fill_time, entry_price=fill_price)
            if trade is None:
                continue  # parite dolu / zaten var / geçersiz pozisyon
            if self.tg is not None:
                self._notify_trade_opened(setup, trade)

    def _reconcile_open(self) -> None:
        """Bootstrap sonrası: açık setup'larda kaçan STOP/TP'yi onar.

        Süreç kapalıyken (restart/deploy/MEXC kesintisi) gerçekleşen çıkışlar
        advance() tek-mum kontrolünden kaçar; setup yanlışlıkla "Aktif" kalır.
        Bu pas tampondaki tüm mumları tarayıp gerçek çıkışları uygular, paper
        defterini de senkronlar (çıkış geçişleri on_transition'dan akar).
        """
        if self.tracker is None or self.poller is None:
            return
        klines = self.poller.buffer.as_list()
        self._in_reconcile = True
        try:
            transitions = self.tracker.reconcile(klines)
        except Exception:
            log.exception("%s reconcile hatası", self._tag)
            return
        finally:
            self._in_reconcile = False
        if transitions:
            log.info("%s reconcile: %d kaçan geçiş onarıldı (%s)", self._tag,
                     len(transitions),
                     ", ".join(f"#{t.setup_id}:{t.new_state}" for t in transitions))

    def _process(self, _closed: dict[str, Any] | None) -> None:
        klines = self.poller.buffer.as_list()
        if len(klines) < 20:
            return
        # Gerçekçi giriş: önceki barda biriken AKTIF setupları bu barın
        # açılışından doldur (tarama/advance'ten önce).
        self._fill_pending_entries(klines[-1])
        htf_klines = self._fetch_htf()
        setups = scan_klines(klines, self.symbol, self.interval,
                             zigzag_threshold=self.threshold, htf_klines=htf_klines)
        for s in setups:
            sid = self.store.upsert_setup(s)
            if self.store.get_lifecycle(sid) is None:
                d_time = s.pivots["D"].time
                tag = "YENI" if d_time >= klines[-3]["open_time"] else "TARIHSEL"
                log.info("%s [%s] %s | id=%d", self._tag, tag, s.summary(), sid)
                self.tracker.register_new(s, sid, klines=klines)
        self.tracker.advance(klines)
        # Potansiyel (henüz oluşmamış) pattern kontrolü — yeni X-A-B-C
        self._check_potential(klines)

    def _check_potential(self, klines: list[dict[str, Any]]) -> None:
        """Son X-A-B-C uyumlu potansiyel pattern varsa Telegram'a kart yolla.
        Dedup: aynı (pivots, pattern) tekrar gönderilmesin diye key tutuluyor.
        """
        if self.no_potential:
            return
        from terminal.detection.pivots import find_pivots
        from terminal.detection.potential import find_potential_patterns
        pivots = find_pivots(klines, self.threshold)
        if len(pivots) < 4:
            return
        matches = find_potential_patterns(pivots[-4:])
        if not matches:
            return
        m = matches[0]
        # DB'ye yaz (UI Potansiyel sekmesinde TÜM TF'ler görünsün) — dedup
        # UNIQUE constraint ile
        try:
            self.store.upsert_potential(self.symbol, self.interval, m)
        except Exception as e:
            log.warning("%s potansiyel DB yazma: %s", self._tag, e)
        # Telegram'a SADECE swing TF'ler (4h, 1d) — kısa TF gürültüsü kapalı.
        if self.tg is None or self.interval not in POTENTIAL_TG_INTERVALS:
            return
        from terminal.telegram_bot.cards import potential_card
        from terminal.telegram_bot.charts import render_potential_chart
        key = (m.spec.name, m.x.time, m.a.time, m.b.time, m.c.time)
        if key == self._last_potential_key:
            return  # zaten gönderildi
        self._last_potential_key = key
        try:
            txt = potential_card(m, self.symbol, self.interval)
            png = None if self.no_chart else render_potential_chart(
                self.symbol, self.interval, klines, zigzag_threshold=self.threshold)
            if png:
                self.tg.send_photo(png, caption=txt, parse_mode="Markdown")
            else:
                self.tg.send_message(txt, parse_mode="Markdown")
            log.info("%s POTANSIYEL gönderildi: %s %s", self._tag,
                     m.spec.name, m.direction)
        except Exception as e:
            log.warning("%s potansiyel kart hatası: %s", self._tag, e)

    def run(self) -> None:
        # Stagger startup → MEXC rate limit'i tampona al
        if self.startup_delay > 0:
            time.sleep(self.startup_delay)
        kaynak = "FUTURES" if self.use_futures else "SPOT"
        log.info("%s başlıyor (%s, ZigZag %.4f)", self._tag, kaynak, self.threshold)
        if self.use_futures:
            self.client = MexcFuturesClient()
        else:
            self.client = MexcClient()
        self.store = Store()
        self.tracker = LifecycleTracker(
            self.symbol, self.interval, self.store, on_transition=self._on_transition,
        )
        self.poller = KlinePoller(
            self.symbol, self.interval, self.client, self.store,
            on_closed=self._process, poll_seconds=self.poll_seconds,
        )
        try:
            self.poller.bootstrap()
            self._reconcile_open()
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


def _load_combos_file(path: Path) -> list[tuple[str, str]]:
    """Parite-TF kombinasyon dosyası: her satırda 'SYMBOL INTERVAL' veya 'SYMBOL,INTERVAL'.
    # ile başlayan satırlar yorum. Cross-product yapmaz; tam kombinasyon listesi döner.
    """
    if not path.exists():
        raise SystemExit(f"Dosya yok: {path}")
    raw = path.read_text(encoding="utf-8").splitlines()
    combos: list[tuple[str, str]] = []
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # virgül veya boşluk ile ayrılabilir
        parts = [p.strip() for p in (s.replace(",", " ").split())]
        if len(parts) != 2:
            raise SystemExit(f"Hatalı satır: {line!r} (beklenen: 'SYMBOL INTERVAL')")
        combos.append((parts[0].upper(), _normalize_interval(parts[1])))
    if not combos:
        raise SystemExit(f"Kombinasyon listesi boş: {path}")
    return combos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-live-multi",
        description="terminalMiraz — Faz 8 (çok parite × çok TF eşzamanlı canlı tarama)",
    )
    parser.add_argument("--symbols", help="Virgülle ayrılmış pariteler")
    parser.add_argument("--symbols-file", help="Her satırda bir parite olan dosya (# yorum)")
    parser.add_argument("--intervals", help="Virgülle ayrılmış aralıklar (örn. 15m,30m,60m,4h)")
    parser.add_argument("--combos-file",
                        help="Parite-TF kombinasyon dosyası: her satırda 'SYMBOL INTERVAL'. "
                             "Verilirse --symbols/--intervals cross-product'ı yerine bu "
                             "kombinasyonlar kullanılır. Örnek: data/tracked_combos.txt")
    parser.add_argument("--zigzag", type=float, default=None)
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-chart", action="store_true")
    parser.add_argument("--min-q", type=int, default=50,
                        help="Bu Q skorunun altındakileri Telegram'a yollama "
                             "(varsayılan 50; 3-ay backtest Q≥50 küçük net pozitif kazanç)")
    parser.add_argument("--min-karakter", type=float, default=0.0,
                        help="Karakter skoru bu eşiğin altında olan (parite, TF, pattern, yön) "
                             "kombinasyonlarını Telegram'a gönderme. Backtest verisi yoksa "
                             "geçer (yeni kombinasyon ihtimaline karşı).")
    parser.add_argument("--min-confluence", type=int, default=70,
                        help="RSI+hacim confluence skorunun altındaki setupları Telegram'a "
                             "yollama. Varsayılan 70 (gerçekçi cost ile net pozitif tek "
                             "eşik). Daha çok bildirim için: 50 veya 0.")
    parser.add_argument("--futures", action="store_true",
                        help="MEXC Futures verisi kullan (default: spot). "
                             "Sembol BTCUSDT → BTC_USDT otomatik dönüşür.")
    parser.add_argument("--paper", action="store_true",
                        help="Paper trade modu — gerçek emir vermeden P&L "
                             "tracking. Her trade $20 risk, leverage SL'e göre.")
    parser.add_argument("--paper-equity", type=float, default=1000.0,
                        help="Paper trade başlangıç sermayesi USD (default 1000).")
    parser.add_argument("--paper-risk", type=float, default=20.0,
                        help="Paper trade başına risk USD (default 20).")
    parser.add_argument("--include-elenen", action="store_true")
    parser.add_argument("--no-potential", action="store_true",
                        help="Potansiyel (oluşmamış) pattern bildirimlerini kapat. "
                             "Default açık: X-A-B-C uyumlu yapılarda 'D bekleniyor' "
                             "kartı Telegram'a yollanır.")
    parser.add_argument("--no-htf", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--stagger-ms", type=int, default=200,
                        help="Her worker arasında bekleme (ms). Bootstrap rate limit'i tampona alır.")
    parser.add_argument("--poll-seconds", type=int, default=POLL_INTERVAL_SECONDS,
                        help=f"Mum yoklama aralığı (sn, varsayılan {POLL_INTERVAL_SECONDS}). "
                             "Çok kombinasyonda (örn. 250) rate limit için 30 önerilir.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # HTTP istemci kütüphaneleri her MEXC çağrısını INFO'da loglayıp logu
    # boğuyor (tracker.err'i şişiren satırlar) — sadece uyarı ve üstünü göster.
    for _noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    # Combos-file > symbols+intervals cross-product
    if args.combos_file:
        combos = _load_combos_file(Path(args.combos_file))
        n_syms = len({c[0] for c in combos})
        n_tfs = len({c[1] for c in combos})
        log.info("Toplam %d kombinasyon (combos-file): %d unique parite, %d unique TF",
                 len(combos), n_syms, n_tfs)
    else:
        if not args.intervals:
            raise SystemExit("--intervals veya --combos-file gerekli")
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

    # Paper trade engine — opsiyonel, paylaşımlı
    paper_engine = None
    if args.paper:
        from terminal.paper.engine import PaperEngine
        shared_store = Store()
        paper_engine = PaperEngine(
            shared_store, initial_equity=args.paper_equity,
            risk_per_trade=args.paper_risk,
        )
        # Açılışta: lifecycle terminal olduğu halde açık kalmış paper trade'leri
        # kapat (stop değdi ama paper açık kaldıysa düzeltir).
        synced = paper_engine.sync_closed_from_lifecycle()
        if synced:
            log.info("PAPER SYNC: %d açık trade lifecycle ile uyumlandı (kapatıldı)",
                     len(synced))
        summary = paper_engine.summary()
        log.info("PAPER TRADE: başlangıç=$%.0f, mevcut=$%.2f, toplam_trade=%d, WR=%.1f%%",
                 summary["initial_equity"], summary["current_equity"],
                 summary["total_trades"], summary["win_rate"])

    workers: list[PairWorker] = []
    threads: list[threading.Thread] = []

    for idx, (sym, iv) in enumerate(combos):
        w = PairWorker(
            symbol=sym, interval=iv, tg=tg,
            min_q=args.min_q, min_karakter=args.min_karakter,
            min_confluence=args.min_confluence,
            include_elenen=args.include_elenen,
            no_chart=args.no_chart, no_potential=args.no_potential,
            use_htf=not args.no_htf,
            zigzag_threshold=args.zigzag,
            use_futures=args.futures, paper_engine=paper_engine,
            startup_delay=idx * (args.stagger_ms / 1000.0),
            poll_seconds=args.poll_seconds,
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
