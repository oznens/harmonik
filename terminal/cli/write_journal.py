"""Faz 7: Günlük Learning Journal yazıcısı.

Bir günün metriklerini DB'den çıkarır, opsiyonel olarak Kiraz'a yorum yazdırır,
journal_entries tablosuna kaydeder.

Kullanım:
    python -m terminal.cli.write_journal                       # bugün, AI ile
    python -m terminal.cli.write_journal --date 2026-05-22     # belirli gün
    python -m terminal.cli.write_journal --no-ai               # sadece istatistik
    python -m terminal.cli.write_journal --last-n 7            # son 7 gün toplu

Her gün cron ile çağrılabilir (UTC 00:05 önerilir).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

from terminal.db.store import Store
from terminal.learning.journal import (
    JournalEntry,
    JournalGenerator,
    format_metrics_for_prompt,
    today_utc,
)
from terminal.timeutil import now_local, yesterday_local


def _yesterday_utc() -> str:
    return yesterday_local()


def _print_summary(date: str, entry: JournalEntry, notes=None) -> None:
    print()
    print("=" * 70)
    print(f"  Learning Journal — {date}")
    print("=" * 70)
    print(format_metrics_for_prompt(entry))
    if notes:
        print()
        print("-- Kiraz Notları --")
        print(f"\n[yorum]\n{notes.yorum}")
        print(f"\n[ders]\n{notes.ders}")
        print(f"\n[yarın için risk modu]\n{notes.yarin_risk_modu}")
    print()


def _process_date(date: str, store: Store, gen: JournalGenerator,
                  use_ai: bool, verbose: bool) -> bool:
    entry = gen.generate(date)
    notes = None
    ai_model = None

    if entry.detected_count == 0 and entry.closed_count == 0:
        logging.info("%s: setup yok, defter girişi yazılmıyor", date)
        return False

    if use_ai:
        from terminal.config import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            logging.warning("ANTHROPIC_API_KEY yok → AI atlanıyor (sadece istatistik)")
        else:
            try:
                from terminal.learning.kiraz import Kiraz, KirazError
                kiraz = Kiraz()
                notes = kiraz.comment(entry)
                ai_model = kiraz.model
            except KirazError as e:
                logging.warning("Kiraz hatası: %s — sadece istatistik yazılıyor", e)
            except Exception as e:
                logging.warning("Kiraz beklenmedik hatası: %s — atlanıyor", e)

    store.upsert_journal(date, entry, ai_notes=notes, ai_model=ai_model)

    if verbose:
        _print_summary(date, entry, notes)
    else:
        ai_tag = f" + Kiraz ({ai_model})" if notes else ""
        print(f"  {date}: {entry.detected_count} tespit, {entry.closed_count} sonuçlandı, "
              f"WR {entry.win_rate*100:.1f}%{ai_tag}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-journal",
        description="terminalMiraz — Faz 7 (Learning Journal + Kiraz)",
    )
    parser.add_argument("--date", help="YYYY-MM-DD (varsayılan: dün UTC)")
    parser.add_argument("--last-n", type=int, default=None,
                        help="Son N günü toplu işle (bugün dahil)")
    parser.add_argument("--no-ai", action="store_true",
                        help="Kiraz'ı (AI) atla, sadece istatistik yaz")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Tam çıktı bas")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    store = Store()
    gen = JournalGenerator(store)
    use_ai = not args.no_ai

    try:
        if args.last_n:
            today = now_local()
            written = 0
            for i in range(args.last_n):
                d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                if _process_date(d, store, gen, use_ai, args.verbose):
                    written += 1
            print(f"\nToplam {written} gün yazıldı.")
        else:
            date = args.date or _yesterday_utc()
            ok = _process_date(date, store, gen, use_ai, verbose=True)
            if not ok:
                print(f"{date}: o gün setup yok, defter girişi yazılmadı.", file=sys.stderr)
                return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
