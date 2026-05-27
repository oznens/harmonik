"""SQLite kalıcı depo. Kline'lar ve tespit edilen Setup'lar burada saklanır."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from terminal.config import DB_PATH

if TYPE_CHECKING:
    from terminal.detection.models import Setup

log = logging.getLogger(__name__)


class Store:
    """SQLite üstüne ince bir sarmalayıcı. Faz 1 boyutunda yeterli."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path) as f:
            self._conn.executescript(f.read())
        self._migrate()

    def _migrate(self) -> None:
        """Eski DB → yeni şema. Sadece eksik kolonları ekler (idempotent)."""
        cur = self._conn.execute("PRAGMA table_info(setups)")
        existing = {row[1] for row in cur.fetchall()}
        # Faz 4 kolonları + confluence
        needed = [
            ("q_score",      "INTEGER"),
            ("q_category",   "TEXT"),
            ("q_components", "TEXT"),
            ("htf_interval", "TEXT"),
            ("htf_trend",    "TEXT"),
            ("htf_aligned",  "INTEGER"),
            ("elenen",       "INTEGER NOT NULL DEFAULT 0"),
            ("confluence_score",      "INTEGER"),
            ("confluence_components", "TEXT"),
            ("rsi_at_d",              "REAL"),
            ("volume_ratio",          "REAL"),
        ]
        for col, definition in needed:
            if col not in existing:
                self._conn.execute(f"ALTER TABLE setups ADD COLUMN {col} {definition}")
        # setup_lifecycle migrasyonu (source kolonu)
        cur = self._conn.execute("PRAGMA table_info(setup_lifecycle)")
        lc_cols = {row[1] for row in cur.fetchall()}
        if "source" not in lc_cols:
            self._conn.execute(
                "ALTER TABLE setup_lifecycle ADD COLUMN source TEXT NOT NULL DEFAULT 'live'"
            )
        # karakter_samples migrasyonu (htf_trend / htf_aligned kolonları)
        cur = self._conn.execute("PRAGMA table_info(karakter_samples)")
        ks_cols = {row[1] for row in cur.fetchall()}
        for col, definition in (("htf_trend", "TEXT"), ("htf_aligned", "INTEGER")):
            if col not in ks_cols:
                self._conn.execute(f"ALTER TABLE karakter_samples ADD COLUMN {col} {definition}")

    def upsert_kline(self, symbol: str, interval: str, k: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO klines
              (symbol, interval, open_time, close_time,
               open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol, interval,
                k["open_time"], k["close_time"],
                k["open"], k["high"], k["low"], k["close"],
                k["volume"], k.get("quote_volume"),
            ),
        )

    def upsert_klines(self, symbol: str, interval: str, klines: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                symbol, interval,
                k["open_time"], k["close_time"],
                k["open"], k["high"], k["low"], k["close"],
                k["volume"], k.get("quote_volume"),
            )
            for k in klines
        ]
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO klines
              (symbol, interval, open_time, close_time,
               open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def latest_open_time(self, symbol: str, interval: str) -> int | None:
        cur = self._conn.execute(
            "SELECT MAX(open_time) FROM klines WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    def count(self, symbol: str, interval: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM klines WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        )
        return int(cur.fetchone()[0])

    # ---- setups -------------------------------------------------------

    def upsert_setup(self, s: "Setup") -> int:
        """Setup'u kaydet (aynı pivot kombinasyonu varsa günceller). id döner."""
        pivots = s.pivots
        self._conn.execute(
            """
            INSERT INTO setups (
                symbol, interval, pattern_name, direction,
                x_time, x_price, a_time, a_price, b_time, b_price,
                c_time, c_price, d_time, d_price,
                b_ratio, c_ratio, d_ratio, bc_proj, cd_ab_ratio, ab_cd_equivalent,
                prz_low, prz_high, prz_components,
                entry, stop, tp1, tp2, detected_at,
                q_score, q_category, q_components,
                htf_interval, htf_trend, htf_aligned, elenen,
                confluence_score, confluence_components, rsi_at_d, volume_ratio
            ) VALUES (?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?, ?,
                      ?, ?, ?, ?)
            ON CONFLICT(symbol, interval, pattern_name, x_time, a_time, b_time, c_time, d_time)
            DO UPDATE SET
                b_ratio=excluded.b_ratio, c_ratio=excluded.c_ratio,
                d_ratio=excluded.d_ratio, bc_proj=excluded.bc_proj,
                cd_ab_ratio=excluded.cd_ab_ratio,
                ab_cd_equivalent=excluded.ab_cd_equivalent,
                prz_low=excluded.prz_low, prz_high=excluded.prz_high,
                prz_components=excluded.prz_components,
                entry=excluded.entry, stop=excluded.stop,
                tp1=excluded.tp1, tp2=excluded.tp2,
                detected_at=excluded.detected_at,
                q_score=excluded.q_score, q_category=excluded.q_category,
                q_components=excluded.q_components,
                htf_interval=excluded.htf_interval, htf_trend=excluded.htf_trend,
                htf_aligned=excluded.htf_aligned, elenen=excluded.elenen,
                confluence_score=excluded.confluence_score,
                confluence_components=excluded.confluence_components,
                rsi_at_d=excluded.rsi_at_d, volume_ratio=excluded.volume_ratio
            """,
            (
                s.symbol, s.interval, s.pattern_name, s.direction,
                pivots["X"].time, pivots["X"].price,
                pivots["A"].time, pivots["A"].price,
                pivots["B"].time, pivots["B"].price,
                pivots["C"].time, pivots["C"].price,
                pivots["D"].time, pivots["D"].price,
                s.b_ratio, s.c_ratio, s.d_ratio, s.bc_proj, s.cd_ab_ratio,
                1 if s.ab_cd_equivalent else 0,
                s.prz_low, s.prz_high, json.dumps(s.prz_components),
                s.entry, s.stop, s.tp1, s.tp2, s.detected_at,
                s.q_score if s.q_score else None,
                s.q_category or None,
                json.dumps(s.q_components) if s.q_components else None,
                s.htf_interval, s.htf_trend,
                (1 if s.htf_aligned else 0) if s.htf_aligned is not None else None,
                1 if s.elenen else 0,
                s.confluence_score if s.confluence_score else None,
                json.dumps(s.confluence_components) if s.confluence_components else None,
                s.rsi_at_d, s.volume_ratio,
            ),
        )
        cur = self._conn.execute(
            """SELECT id FROM setups
               WHERE symbol=? AND interval=? AND pattern_name=?
                 AND x_time=? AND a_time=? AND b_time=? AND c_time=? AND d_time=?""",
            (s.symbol, s.interval, s.pattern_name,
             pivots["X"].time, pivots["A"].time, pivots["B"].time,
             pivots["C"].time, pivots["D"].time),
        )
        row = cur.fetchone()
        return int(row[0]) if row else -1

    def count_setups(self, symbol: str | None = None, interval: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM setups WHERE 1=1"
        params: list[Any] = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if interval:
            sql += " AND interval = ?"
            params.append(interval)
        cur = self._conn.execute(sql, params)
        return int(cur.fetchone()[0])

    def load_setup(self, setup_id: int) -> "Setup | None":
        """DB'den setup'ı Setup nesnesi olarak yükle (lifecycle tarafı için)."""
        from terminal.detection.models import Setup
        from terminal.detection.pivots import Pivot

        cur = self._conn.execute("SELECT * FROM setups WHERE id = ?", (setup_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = row.keys()
        htf_aligned_raw = row["htf_aligned"] if "htf_aligned" in cols else None
        return Setup(
            symbol=row["symbol"],
            interval=row["interval"],
            pattern_name=row["pattern_name"],
            direction=row["direction"],
            pivots={
                "X": Pivot(0, row["x_time"], row["x_price"], "low" if row["direction"] == "bull" else "high"),
                "A": Pivot(0, row["a_time"], row["a_price"], "high" if row["direction"] == "bull" else "low"),
                "B": Pivot(0, row["b_time"], row["b_price"], "low" if row["direction"] == "bull" else "high"),
                "C": Pivot(0, row["c_time"], row["c_price"], "high" if row["direction"] == "bull" else "low"),
                "D": Pivot(0, row["d_time"], row["d_price"], "low" if row["direction"] == "bull" else "high"),
            },
            b_ratio=row["b_ratio"], c_ratio=row["c_ratio"], d_ratio=row["d_ratio"],
            bc_proj=row["bc_proj"], cd_ab_ratio=row["cd_ab_ratio"],
            ab_cd_equivalent=bool(row["ab_cd_equivalent"]),
            prz_low=row["prz_low"], prz_high=row["prz_high"],
            prz_components=json.loads(row["prz_components"]),
            entry=row["entry"], stop=row["stop"], tp1=row["tp1"], tp2=row["tp2"],
            detected_at=row["detected_at"],
            q_score=row["q_score"] or 0,
            q_category=row["q_category"] or "",
            q_components=json.loads(row["q_components"]) if row["q_components"] else {},
            htf_interval=row["htf_interval"],
            htf_trend=row["htf_trend"],
            htf_aligned=bool(htf_aligned_raw) if htf_aligned_raw is not None else None,
            elenen=bool(row["elenen"]),
        )

    # ---- lifecycle ----

    def upsert_lifecycle(
        self, setup_id: int, state: str, state_changed_at: int,
        entered_at: int | None = None, exited_at: int | None = None,
        exit_reason: str | None = None, source: str | None = None,
    ) -> None:
        """Lifecycle satırı upsert. entered_at/source None ise mevcut değer korunur."""
        # source default 'live' — INSERT'te eklemiyorsak DEFAULT devreye girer.
        self._conn.execute(
            """
            INSERT INTO setup_lifecycle
              (setup_id, state, state_changed_at, entered_at, exited_at, exit_reason, source)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 'live'))
            ON CONFLICT(setup_id) DO UPDATE SET
              state = excluded.state,
              state_changed_at = excluded.state_changed_at,
              entered_at = COALESCE(excluded.entered_at, setup_lifecycle.entered_at),
              exited_at  = COALESCE(excluded.exited_at,  setup_lifecycle.exited_at),
              exit_reason = COALESCE(excluded.exit_reason, setup_lifecycle.exit_reason),
              source = COALESCE(?, setup_lifecycle.source)
            """,
            (setup_id, state, state_changed_at, entered_at, exited_at, exit_reason,
             source, source),
        )

    def get_lifecycle(self, setup_id: int) -> sqlite3.Row | None:
        cur = self._conn.execute("SELECT * FROM setup_lifecycle WHERE setup_id = ?", (setup_id,))
        return cur.fetchone()

    def open_setups(self, symbol: str, interval: str) -> list[sqlite3.Row]:
        """Aday veya Aktif durumdaki tüm setup'lar (bu symbol/interval için)."""
        cur = self._conn.execute(
            """
            SELECT l.* FROM setup_lifecycle l
            JOIN setups s ON s.id = l.setup_id
            WHERE s.symbol = ? AND s.interval = ?
              AND l.state IN ('Aday', 'Aktif')
            ORDER BY l.state_changed_at DESC
            """,
            (symbol, interval),
        )
        return cur.fetchall()

    def add_event(
        self, setup_id: int, prev: str | None, new: str, ev_time: int,
        price: float | None, notes: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO setup_events (setup_id, event_time, prev_state, new_state, trigger_price, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (setup_id, ev_time, prev, new, price, notes),
        )

    def mark_notified(self, setup_id: int, field: str) -> None:
        """field: 'aday' | 'aktif' | 'exit'."""
        col = {"aday": "notified_aday", "aktif": "notified_aktif", "exit": "notified_exit"}[field]
        self._conn.execute(
            f"UPDATE setup_lifecycle SET {col} = 1 WHERE setup_id = ?",
            (setup_id,),
        )

    # ---- karakter lab ----

    def create_karakter_run(
        self, started_at: int, bars_per_pair: int,
        symbols: list[str], intervals: list[str], notes: str = "",
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO karakter_runs (started_at, bars_per_pair, symbols, intervals, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (started_at, bars_per_pair, json.dumps(symbols), json.dumps(intervals), notes),
        )
        return int(cur.lastrowid)

    def finish_karakter_run(self, run_id: int, sample_count: int) -> None:
        self._conn.execute(
            """UPDATE karakter_runs SET finished_at = ?, sample_count = ? WHERE id = ?""",
            (int(time.time() * 1000), sample_count, run_id),
        )

    def add_karakter_sample(self, run_id: int, setup: "Setup", outcome) -> None:
        # outcome: SimOutcome (terminal.karakter.simulator)

        # 1) Setup'ı setups tablosuna yaz (idempotent — aynı pivotlar varsa id döner)
        setup_id = self.upsert_setup(setup)

        # 2) Outcome'a göre setup_lifecycle güncelle (UI Sonuçlar sekmesinde görünsün)
        state = outcome.outcome
        state_changed_at = outcome.exited_time or outcome.entered_time or setup.detected_at
        self.upsert_lifecycle(
            setup_id=setup_id,
            state=state,
            state_changed_at=state_changed_at,
            entered_at=outcome.entered_time,
            exited_at=outcome.exited_time,
            exit_reason=f"lab run #{run_id}" if state in ("TP", "STOP", "EO", "ZI") else None,
            source="backtest",
        )

        # 3) Karakter sample tablosuna da yaz (lab-spesifik istatistik)
        htf_aligned_int: int | None
        if setup.htf_aligned is None:
            htf_aligned_int = None
        else:
            htf_aligned_int = 1 if setup.htf_aligned else 0
        self._conn.execute(
            """INSERT INTO karakter_samples
               (run_id, symbol, interval, pattern_name, direction,
                d_time, d_price, entry, stop, tp1, q_score,
                outcome, entered_at, exited_at, ambiguous,
                htf_trend, htf_aligned)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, setup.symbol, setup.interval, setup.pattern_name, setup.direction,
                setup.pivots["D"].time, setup.pivots["D"].price,
                setup.entry, setup.stop, setup.tp1,
                setup.q_score or None,
                outcome.outcome, outcome.entered_time, outcome.exited_time,
                1 if outcome.ambiguous else 0,
                setup.htf_trend, htf_aligned_int,
            ),
        )

    def recompute_karakter_scores(self) -> int:
        """karakter_samples'tan karakter_scores tablosunu yeniden oluştur.

        Hem direction='all' (toplam) hem bull/bear ayrıştırılmış kayıt üretir.
        """
        now = int(time.time() * 1000)
        from terminal.karakter.score import compute_stats

        # Tüm grupları topla
        cur = self._conn.execute(
            """SELECT symbol, interval, pattern_name, direction, outcome
               FROM karakter_samples"""
        )
        # (symbol, interval, pattern, direction_key) → list[outcome]
        buckets: dict[tuple[str, str, str, str], list[str]] = {}
        for row in cur.fetchall():
            sym, iv, pat, dirn, oc = row
            for dkey in (dirn, "all"):
                key = (sym, iv, pat, dkey)
                buckets.setdefault(key, []).append(oc)

        # Eski skorları temizle
        self._conn.execute("DELETE FROM karakter_scores")

        rows = 0
        for (sym, iv, pat, dirn), outcomes in buckets.items():
            stats = compute_stats(outcomes)
            self._conn.execute(
                """INSERT INTO karakter_scores
                   (symbol, interval, pattern_name, direction,
                    sample_count, tp_count, stop_count, eo_count, zi_count,
                    open_count, win_rate, karakter_score, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sym, iv, pat, dirn,
                 stats.sample_count, stats.tp_count, stats.stop_count,
                 stats.eo_count, stats.zi_count, stats.open_count,
                 stats.win_rate, stats.karakter_score, now),
            )
            rows += 1
        return rows

    def get_karakter_score(
        self, symbol: str, interval: str, pattern_name: str, direction: str = "all",
    ) -> tuple[float, int] | None:
        """(karakter_score, sample_count) döner. Kayıt yoksa None."""
        cur = self._conn.execute(
            """SELECT karakter_score, sample_count FROM karakter_scores
               WHERE symbol=? AND interval=? AND pattern_name=? AND direction=?""",
            (symbol, interval, pattern_name, direction),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return float(row[0] or 0), int(row[1] or 0)

    # ---- journal (Faz 7) ----

    def upsert_journal(
        self, date: str, entry, ai_notes=None, ai_model: str | None = None,
    ) -> None:
        """JournalEntry + opsiyonel KirazNotes → journal_entries upsert.

        Args:
            date: YYYY-MM-DD
            entry: terminal.learning.journal.JournalEntry
            ai_notes: terminal.learning.kiraz.KirazNotes veya None
            ai_model: kullanılan Claude modeli (örn. "claude-opus-4-7")
        """
        from dataclasses import asdict
        # JournalEntry'i serialize et — by_pattern vs için OutcomeBreakdown'lar dict'e dönsün
        metrics = {
            "by_pattern":     {k: asdict(v) for k, v in entry.by_pattern.items()},
            "by_interval":    {k: asdict(v) for k, v in entry.by_interval.items()},
            "by_direction":   {k: asdict(v) for k, v in entry.by_direction.items()},
            "by_q_category":  {k: asdict(v) for k, v in entry.by_q_category.items()},
            "best_pattern_wr": entry.best_pattern_wr,
            "worst_pattern_wr": entry.worst_pattern_wr,
        }
        self._conn.execute(
            """INSERT INTO journal_entries
                 (date, detected_count, closed_count, tp_count, stop_count, eo_count, zi_count,
                  win_rate, metrics_json, best_pattern, worst_pattern,
                  ai_yorum, ai_ders, ai_yarin_risk, ai_model, written_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                  detected_count=excluded.detected_count,
                  closed_count=excluded.closed_count,
                  tp_count=excluded.tp_count, stop_count=excluded.stop_count,
                  eo_count=excluded.eo_count, zi_count=excluded.zi_count,
                  win_rate=excluded.win_rate, metrics_json=excluded.metrics_json,
                  best_pattern=excluded.best_pattern, worst_pattern=excluded.worst_pattern,
                  ai_yorum=COALESCE(excluded.ai_yorum, journal_entries.ai_yorum),
                  ai_ders=COALESCE(excluded.ai_ders, journal_entries.ai_ders),
                  ai_yarin_risk=COALESCE(excluded.ai_yarin_risk, journal_entries.ai_yarin_risk),
                  ai_model=COALESCE(excluded.ai_model, journal_entries.ai_model),
                  written_at=excluded.written_at
            """,
            (
                date, entry.detected_count, entry.closed_count,
                entry.tp, entry.stop, entry.eo, entry.zi,
                entry.win_rate, json.dumps(metrics),
                entry.best_pattern, entry.worst_pattern,
                ai_notes.yorum if ai_notes else None,
                ai_notes.ders if ai_notes else None,
                ai_notes.yarin_risk_modu if ai_notes else None,
                ai_model,
                int(time.time() * 1000),
            ),
        )

    def get_journal(self, date: str) -> sqlite3.Row | None:
        cur = self._conn.execute("SELECT * FROM journal_entries WHERE date = ?", (date,))
        return cur.fetchone()

    def list_journals(self, limit: int = 30) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM journal_entries ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    # ---- outcome override (Faz 8) ----

    def override_outcome(
        self, setup_id: int, override_state: str, reason: str = "",
    ) -> None:
        """Bir setup'ın outcome'unu manuel düzelt.

        - outcome_overrides tablosuna audit kaydı ekler (eski state'i de saklar)
        - setup_lifecycle.state'i günceller
        - setup_events'a "manuel düzeltme" girişi düşer
        """
        # Mevcut state'i al
        row = self.get_lifecycle(setup_id)
        original = row["state"] if row else None
        if original == override_state:
            return  # değişiklik yok

        now = int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO outcome_overrides (setup_id, original_state, override_state, reason, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (setup_id, original or "?", override_state, reason or "", now),
        )
        # Lifecycle state güncelle
        if row is not None:
            self._conn.execute(
                """UPDATE setup_lifecycle
                   SET state = ?, state_changed_at = ?, exit_reason = ?
                   WHERE setup_id = ?""",
                (override_state, now, f"manuel: {reason}" if reason else "manuel düzeltme", setup_id),
            )
        else:
            self.upsert_lifecycle(
                setup_id=setup_id, state=override_state,
                state_changed_at=now,
                exit_reason=f"manuel: {reason}" if reason else "manuel düzeltme",
            )
        # Audit event
        self._conn.execute(
            """INSERT INTO setup_events (setup_id, event_time, prev_state, new_state, trigger_price, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (setup_id, now, original, override_state, None,
             f"manuel düzeltme: {reason}" if reason else "manuel düzeltme"),
        )

    def get_overrides(self, setup_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """SELECT * FROM outcome_overrides WHERE setup_id = ?
               ORDER BY created_at DESC, id DESC""",
            (setup_id,),
        )
        return cur.fetchall()

    def count_overrides(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM outcome_overrides").fetchone()[0])

    def lifecycle_stats(self, symbol: str | None = None, interval: str | None = None) -> dict[str, int]:
        sql = """SELECT l.state, COUNT(*) as n FROM setup_lifecycle l
                 JOIN setups s ON s.id = l.setup_id WHERE 1=1"""
        params: list[Any] = []
        if symbol:
            sql += " AND s.symbol = ?"; params.append(symbol)
        if interval:
            sql += " AND s.interval = ?"; params.append(interval)
        sql += " GROUP BY l.state"
        cur = self._conn.execute(sql, params)
        return {row["state"]: int(row["n"]) for row in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()
