"""Journal generator + Kiraz schema testleri.

Anthropic API çağrısı yapmaz — sadece DB sorguları ve Pydantic doğrulaması.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from terminal.db.store import Store
from terminal.detection.scanner import scan_klines
from terminal.learning.journal import (
    JournalGenerator,
    day_bounds_ms,
    format_metrics_for_prompt,
    parse_date,
)
from terminal.lifecycle.states import EO, STOP, TP
from terminal.lifecycle.tracker import LifecycleTracker
from tests.synthetic import gartley_bull, make_xabcd_klines


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(path=tmp_path / "test.db")
    yield s
    s.close()


# ---- date helpers ----

def test_parse_date():
    d = parse_date("2026-05-22")
    assert d.year == 2026 and d.month == 5 and d.day == 22
    # Artık DISPLAY_TZ (Europe/Istanbul varsayılan) zaman dilimi taşır
    assert d.tzinfo is not None


def test_day_bounds_ms():
    start, end = day_bounds_ms("2026-05-22")
    # 24 saatlik aralık (DST yoksa)
    assert end - start == 24 * 3600 * 1000
    # Start, local midnight'a karşılık gelmeli
    from terminal.timeutil import TZ
    expected_start = int(datetime(2026, 5, 22, tzinfo=TZ).timestamp() * 1000)
    assert start == expected_start


# ---- JournalGenerator ----

def test_generate_empty_day(store: Store):
    gen = JournalGenerator(store)
    entry = gen.generate("2026-05-22")
    assert entry.detected_count == 0
    assert entry.closed_count == 0
    assert entry.tp == 0
    assert entry.win_rate == 0.0


_seed_counter = [0]


def _seed_setup_with_outcome(store: Store, day_iso: str, outcome: str, pattern: str = "Gartley"):
    """Bir setup yarat ve verilen günde verilen outcome ile sonuçlandır.

    Her çağrı benzersiz pivot zamanları üretir. min_rr=0 ile filtre bypass
    edilir — sentetik ideal Gartley TP=B yapısal olarak yakın (R:R<1).
    """
    _seed_counter[0] += 1
    prices, kinds = gartley_bull()
    base_time = 1_700_000_000_000 + _seed_counter[0] * 10_000_000_000
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=base_time)
    setups = scan_klines(klines, "TESTUSDT", "60m", zigzag_threshold=0.01, min_rr=0.0)
    s = next(x for x in setups if x.pattern_name == pattern)
    day_start = int(parse_date(day_iso).timestamp() * 1000) + 3600 * 1000
    s.detected_at = day_start
    sid = store.upsert_setup(s)
    store.upsert_lifecycle(
        setup_id=sid, state=outcome,
        state_changed_at=day_start,
        entered_at=day_start if outcome in (TP, STOP) else None,
        exited_at=day_start + 3600 * 1000,
        exit_reason=outcome.lower(),
    )
    return sid


def test_generate_with_mixed_outcomes(store: Store):
    day = "2026-05-22"
    # 3 TP + 1 STOP + 1 EO
    for _ in range(3):
        _seed_setup_with_outcome(store, day, TP)
    _seed_setup_with_outcome(store, day, STOP)
    _seed_setup_with_outcome(store, day, EO)

    gen = JournalGenerator(store)
    entry = gen.generate(day)
    assert entry.closed_count == 5
    assert entry.tp == 3 and entry.stop == 1 and entry.eo == 1
    assert abs(entry.win_rate - 0.75) < 1e-6  # 3/(3+1)


def test_generate_by_pattern_breakdown(store: Store):
    day = "2026-05-22"
    _seed_setup_with_outcome(store, day, TP, pattern="Gartley")
    _seed_setup_with_outcome(store, day, STOP, pattern="Gartley")

    gen = JournalGenerator(store)
    entry = gen.generate(day)
    assert "Gartley" in entry.by_pattern
    br = entry.by_pattern["Gartley"]
    assert br.tp == 1 and br.stop == 1
    assert abs(br.win_rate - 0.5) < 1e-6


def test_best_worst_pattern_needs_min_samples(store: Store):
    day = "2026-05-22"
    # Sadece 1 sonuç → best/worst hesaplanmamalı (min 3 kararlı)
    _seed_setup_with_outcome(store, day, TP)
    gen = JournalGenerator(store)
    entry = gen.generate(day)
    assert entry.best_pattern is None
    assert entry.worst_pattern is None


def test_format_metrics_for_prompt(store: Store):
    day = "2026-05-22"
    _seed_setup_with_outcome(store, day, TP)
    _seed_setup_with_outcome(store, day, STOP)
    gen = JournalGenerator(store)
    entry = gen.generate(day)
    text = format_metrics_for_prompt(entry)
    assert "Tarih: 2026-05-22" in text
    assert "TP: 1" in text
    assert "STOP: 1" in text
    assert "Pattern bazında" in text


# ---- Store: journal upsert ----

def test_store_upsert_journal_without_ai(store: Store):
    day = "2026-05-22"
    _seed_setup_with_outcome(store, day, TP)
    _seed_setup_with_outcome(store, day, STOP)

    gen = JournalGenerator(store)
    entry = gen.generate(day)
    store.upsert_journal(day, entry, ai_notes=None)

    row = store.get_journal(day)
    assert row is not None
    assert row["tp_count"] == 1
    assert row["stop_count"] == 1
    assert row["ai_yorum"] is None  # AI yok


def test_store_upsert_journal_with_ai(store: Store):
    from terminal.learning.kiraz import KirazNotes
    day = "2026-05-22"
    _seed_setup_with_outcome(store, day, TP)
    gen = JournalGenerator(store)
    entry = gen.generate(day)

    notes = KirazNotes(
        yorum="Bugün tek TP geldi, örneklem yetersiz.",
        ders="Bir günlük WR güvenilmez.",
        yarin_risk_modu="Normal mod.",
    )
    store.upsert_journal(day, entry, ai_notes=notes, ai_model="claude-opus-4-7")

    row = store.get_journal(day)
    assert row["ai_yorum"].startswith("Bugün tek")
    assert row["ai_ders"].startswith("Bir günlük")
    assert row["ai_model"] == "claude-opus-4-7"


def test_upsert_journal_idempotent(store: Store):
    """Aynı günü iki kez yazınca tek satır kalır (upsert)."""
    day = "2026-05-22"
    _seed_setup_with_outcome(store, day, TP)
    gen = JournalGenerator(store)
    entry = gen.generate(day)
    store.upsert_journal(day, entry)
    store.upsert_journal(day, entry)
    cur = store._conn.execute("SELECT COUNT(*) FROM journal_entries WHERE date = ?", (day,))
    assert cur.fetchone()[0] == 1


# ---- Kiraz schema (Pydantic validation) ----

def test_kiraz_notes_schema_validates():
    from terminal.learning.kiraz import KirazNotes
    notes = KirazNotes(
        yorum="Test yorumu.",
        ders="Test dersi.",
        yarin_risk_modu="Test risk modu.",
    )
    assert notes.yorum == "Test yorumu."


def test_kiraz_notes_schema_rejects_missing_field():
    from pydantic import ValidationError

    from terminal.learning.kiraz import KirazNotes
    with pytest.raises(ValidationError):
        KirazNotes(yorum="x", ders="y")  # eksik yarin_risk_modu
