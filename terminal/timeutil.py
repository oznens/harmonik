"""Zaman dilimi yardımcıları.

İç saklama (DB) UTC milisaniye olarak yapılır; kullanıcıya gösterimde
bu modüldeki fonksiyonlardan geçilir. DISPLAY_TZ (.env veya varsayılan
"Europe/Istanbul") ile global olarak ayarlanır.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from terminal.config import DISPLAY_TZ

# Tek noktadan ZoneInfo nesnesi
try:
    TZ = ZoneInfo(DISPLAY_TZ)
except Exception:  # geçersiz TZ adı verildiyse UTC'ye düş
    TZ = ZoneInfo("UTC")


def _tz_tag() -> str:
    """Görüntü için kısa zaman dilimi etiketi (örn. '+03', 'UTC')."""
    if DISPLAY_TZ.upper() == "UTC":
        return "UTC"
    # offset → +03, -05 vs.
    offset = datetime.now(tz=TZ).utcoffset()
    if offset is None:
        return ""
    total_min = int(offset.total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    h = abs(total_min) // 60
    m = abs(total_min) % 60
    return f"{sign}{h:02d}:{m:02d}" if m else f"{sign}{h:02d}"


_TZ_TAG = _tz_tag()


def to_local(ms: int) -> datetime:
    """ms timestamp → DISPLAY_TZ datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=TZ)


def format_local(ms: int) -> str:
    """'2026-05-22 16:45 +03' formatı."""
    return to_local(ms).strftime(f"%Y-%m-%d %H:%M {_TZ_TAG}").rstrip()


def format_local_short(ms: int) -> str:
    """'05-22 16:45' formatı (tablo kolonları için)."""
    return to_local(ms).strftime("%m-%d %H:%M")


def format_local_date(ms: int) -> str:
    """'2026-05-22' formatı."""
    return to_local(ms).strftime("%Y-%m-%d")


def now_local() -> datetime:
    return datetime.now(tz=TZ)


def today_local() -> str:
    """Bugünün DISPLAY_TZ'ye göre tarihi (YYYY-MM-DD)."""
    return now_local().strftime("%Y-%m-%d")


def yesterday_local() -> str:
    return (now_local() - timedelta(days=1)).strftime("%Y-%m-%d")


def parse_local_date(s: str) -> datetime:
    """'YYYY-MM-DD' → DISPLAY_TZ midnight datetime."""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=TZ)


def day_bounds_ms(date: str) -> tuple[int, int]:
    """Verilen YYYY-MM-DD için DISPLAY_TZ midnight'tan sonraki günün
    midnight'ına kadar [start_ms, end_ms) UTC sınırları."""
    start = parse_local_date(date)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def start_of_today_ms() -> int:
    """Bugünün (DISPLAY_TZ) midnight'ı UTC ms olarak."""
    return day_bounds_ms(today_local())[0]


TZ_TAG = _TZ_TAG  # public re-export
