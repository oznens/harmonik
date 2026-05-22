"""Learning Journal: bir günün setup performans metriklerini DB'den çıkarır.

JournalGenerator, kuru istatistik üretmek için saf SQL kullanır — AI yorumu
ayrı bir katmandadır (terminal/learning/kiraz.py). Bu sayede AI olmadan da
istatistik üretip not düşülebilir (--no-ai modu).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from terminal.db.store import Store


def parse_date(s: str) -> datetime:
    """YYYY-MM-DD → UTC midnight datetime."""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def day_bounds_ms(date: str) -> tuple[int, int]:
    """Verilen YYYY-MM-DD için [start_ms, end_ms) UTC sınırları."""
    start = parse_date(date)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def today_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class OutcomeBreakdown:
    """Bir grup (parite, TF, pattern, vs) için TP/STOP/EO/ZI sayıları."""
    key: str
    tp: int = 0
    stop: int = 0
    eo: int = 0
    zi: int = 0
    open: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.stop + self.eo + self.zi + self.open

    @property
    def decided(self) -> int:
        return self.tp + self.stop

    @property
    def win_rate(self) -> float:
        return self.tp / self.decided if self.decided > 0 else 0.0


@dataclass
class JournalEntry:
    """Bir günün özetlenmiş metrikleri."""
    date: str                          # YYYY-MM-DD UTC
    detected_count: int = 0            # gün içinde tespit edilen setup sayısı
    closed_count: int = 0              # gün içinde sonuçlanan (TP/STOP/EO/ZI) setup sayısı
    tp: int = 0
    stop: int = 0
    eo: int = 0
    zi: int = 0
    win_rate: float = 0.0              # TP / (TP+STOP), zamansal hariç

    by_pattern: dict[str, OutcomeBreakdown] = field(default_factory=dict)
    by_interval: dict[str, OutcomeBreakdown] = field(default_factory=dict)
    by_direction: dict[str, OutcomeBreakdown] = field(default_factory=dict)
    by_q_category: dict[str, OutcomeBreakdown] = field(default_factory=dict)

    best_pattern: str | None = None
    best_pattern_wr: float = 0.0
    worst_pattern: str | None = None
    worst_pattern_wr: float = 0.0


class JournalGenerator:
    """DB'den bir gün için JournalEntry üretir."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def generate(self, date: str) -> JournalEntry:
        start_ms, end_ms = day_bounds_ms(date)
        entry = JournalEntry(date=date)

        c = self.store._conn

        # 1) Gün içinde tespit edilen
        cur = c.execute(
            "SELECT COUNT(*) FROM setups WHERE detected_at >= ? AND detected_at < ?",
            (start_ms, end_ms),
        )
        entry.detected_count = int(cur.fetchone()[0])

        # 2) Gün içinde sonuçlanan (lifecycle exited_at bu gün içindeyse)
        cur = c.execute(
            """SELECT s.pattern_name, s.interval, s.direction, s.q_category, l.state
               FROM setups s
               JOIN setup_lifecycle l ON l.setup_id = s.id
               WHERE l.exited_at >= ? AND l.exited_at < ?""",
            (start_ms, end_ms),
        )
        for pat, iv, dirn, qcat, state in cur.fetchall():
            entry.closed_count += 1
            self._tally(entry.by_pattern, pat, state)
            self._tally(entry.by_interval, iv, state)
            self._tally(entry.by_direction, dirn, state)
            if qcat:
                self._tally(entry.by_q_category, qcat, state)
            if state == "TP":   entry.tp += 1
            elif state == "STOP": entry.stop += 1
            elif state == "EO":   entry.eo += 1
            elif state == "ZI":   entry.zi += 1

        decided = entry.tp + entry.stop
        entry.win_rate = (entry.tp / decided) if decided > 0 else 0.0

        # 3) En iyi / en zayıf pattern (min 3 kararlı örneklem)
        for pat, br in entry.by_pattern.items():
            if br.decided < 3:
                continue
            if br.win_rate > entry.best_pattern_wr:
                entry.best_pattern_wr = br.win_rate
                entry.best_pattern = pat
            if entry.worst_pattern is None or br.win_rate < entry.worst_pattern_wr:
                entry.worst_pattern_wr = br.win_rate
                entry.worst_pattern = pat

        return entry

    @staticmethod
    def _tally(d: dict[str, OutcomeBreakdown], key: str, state: str) -> None:
        if key not in d:
            d[key] = OutcomeBreakdown(key=key)
        br = d[key]
        if state == "TP":   br.tp += 1
        elif state == "STOP": br.stop += 1
        elif state == "EO":   br.eo += 1
        elif state == "ZI":   br.zi += 1
        else:                 br.open += 1


def format_metrics_for_prompt(entry: JournalEntry) -> str:
    """JournalEntry'i Claude'a metin olarak özetler (yapılandırılmış prompt için)."""
    lines = [
        f"Tarih: {entry.date} (UTC)",
        f"Bugün tespit edilen setup: {entry.detected_count}",
        f"Bugün sonuçlanan setup: {entry.closed_count}",
        f"  TP: {entry.tp}, STOP: {entry.stop}, EO (Entry Olmadı): {entry.eo}, ZI (Zamansal İptal): {entry.zi}",
        f"  Win Rate (TP/(TP+STOP)): {entry.win_rate*100:.1f}%" if (entry.tp + entry.stop) else
        "  Win Rate: hesaplanamadı (kararlı sonuç yok)",
    ]

    def _section(title: str, d: dict[str, OutcomeBreakdown]):
        if not d:
            return
        lines.append(f"\n{title}:")
        for k, br in sorted(d.items(), key=lambda kv: kv[1].total, reverse=True):
            lines.append(
                f"  {k}: TP {br.tp} | STOP {br.stop} | EO {br.eo} | ZI {br.zi} "
                f"| WR {br.win_rate*100:.0f}%" if br.decided else
                f"  {k}: TP {br.tp} | STOP {br.stop} | EO {br.eo} | ZI {br.zi}"
            )

    _section("Pattern bazında", entry.by_pattern)
    _section("Zaman dilimi bazında", entry.by_interval)
    _section("Yön bazında", entry.by_direction)
    _section("Q kategorisi bazında", entry.by_q_category)

    if entry.best_pattern:
        lines.append(f"\nEn iyi çalışan yapı: {entry.best_pattern} (WR {entry.best_pattern_wr*100:.0f}%)")
    if entry.worst_pattern:
        lines.append(f"Zayıf kalan yapı: {entry.worst_pattern} (WR {entry.worst_pattern_wr*100:.0f}%)")

    return "\n".join(lines)
