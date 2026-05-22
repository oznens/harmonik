"""Karakter raporları: günün/7gün/30gün sıralamaları.

DB'deki karakter_scores tablosundan beslenir. Her satır bir (symbol, interval,
pattern, direction) için aggregated sample/WR/karakter_score içerir.
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.db.store import Store


@dataclass
class KarakterRow:
    symbol: str
    interval: str
    pattern_name: str
    direction: str
    sample_count: int
    tp_count: int
    stop_count: int
    eo_count: int
    zi_count: int
    win_rate: float
    karakter_score: float


def top_by_pattern(store: Store, n: int = 10) -> list[KarakterRow]:
    """En yüksek karakter skoruna sahip (parite + pattern) eşleşmeleri."""
    cur = store._conn.execute(
        """SELECT symbol, interval, pattern_name, direction,
                  sample_count, tp_count, stop_count, eo_count, zi_count,
                  win_rate, karakter_score
           FROM karakter_scores
           WHERE direction != 'all'
           ORDER BY karakter_score DESC
           LIMIT ?""",
        (n,),
    )
    return [_row_to_obj(r) for r in cur.fetchall()]


def top_pairs_for_pattern(store: Store, pattern_name: str, n: int = 10) -> list[KarakterRow]:
    """Belirli bir formasyon için en başarılı pariteler."""
    cur = store._conn.execute(
        """SELECT symbol, interval, pattern_name, direction,
                  sample_count, tp_count, stop_count, eo_count, zi_count,
                  win_rate, karakter_score
           FROM karakter_scores
           WHERE pattern_name = ? AND direction = 'all'
           ORDER BY karakter_score DESC
           LIMIT ?""",
        (pattern_name, n),
    )
    return [_row_to_obj(r) for r in cur.fetchall()]


def top_patterns_for_pair(store: Store, symbol: str, n: int = 10) -> list[KarakterRow]:
    """Belirli bir parite için en başarılı formasyonlar."""
    cur = store._conn.execute(
        """SELECT symbol, interval, pattern_name, direction,
                  sample_count, tp_count, stop_count, eo_count, zi_count,
                  win_rate, karakter_score
           FROM karakter_scores
           WHERE symbol = ? AND direction = 'all'
           ORDER BY karakter_score DESC
           LIMIT ?""",
        (symbol, n),
    )
    return [_row_to_obj(r) for r in cur.fetchall()]


def _row_to_obj(row) -> KarakterRow:
    return KarakterRow(
        symbol=row[0], interval=row[1], pattern_name=row[2], direction=row[3],
        sample_count=int(row[4]), tp_count=int(row[5]), stop_count=int(row[6]),
        eo_count=int(row[7]), zi_count=int(row[8]),
        win_rate=float(row[9] or 0.0), karakter_score=float(row[10] or 0.0),
    )
