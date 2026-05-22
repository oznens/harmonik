"""SQLite kalıcı depo. Kline'lar ve tespit edilen Setup'lar burada saklanır."""
from __future__ import annotations

import json
import logging
import sqlite3
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
                entry, stop, tp1, tp2, detected_at
            ) VALUES (?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?,
                      ?, ?, ?,
                      ?, ?, ?, ?, ?)
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
                detected_at=excluded.detected_at
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

    def close(self) -> None:
        self._conn.close()
