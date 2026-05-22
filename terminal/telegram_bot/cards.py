"""Setup → Telegram mesaj kartı formatlayıcısı (Markdown)."""
from __future__ import annotations

from datetime import datetime, timezone

from terminal.detection.models import Setup


def _fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _arrow(direction: str) -> str:
    return "▲ BULL" if direction == "bull" else "▼ BEAR"


def _abs_pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100 if b else 0.0


def aday_card(setup: Setup) -> str:
    """Aday setup için (yeni tespit edildi, henüz fiyat PRZ'ye girmedi)."""
    s = setup
    d_time = s.pivots["D"].time
    risk_pct = _abs_pct(s.stop, s.entry)
    reward1_pct = _abs_pct(s.tp1, s.entry)
    rr = reward1_pct / risk_pct if risk_pct else 0.0

    lines = [
        f"*ADAY SETUP* {_arrow(s.direction)}",
        f"*{s.symbol}* `{s.interval}` — `{s.pattern_name}`",
        "",
        f"PRZ: `{s.prz_low:.6g} – {s.prz_high:.6g}`",
        f"Entry: `{s.entry:.6g}`",
        f"SL: `{s.stop:.6g}` ({risk_pct:.2f}%)",
        f"TP1: `{s.tp1:.6g}` ({reward1_pct:.2f}%) · R:R `{rr:.2f}`",
        f"TP2: `{s.tp2:.6g}`",
        "",
        f"B={s.b_ratio:.3f}  D={s.d_ratio:.3f}"
        + ("  AB=CD ✓" if s.ab_cd_equivalent else ""),
        f"D pivot: `{_fmt(d_time)}`",
    ]
    return "\n".join(lines)


def aktif_card(setup: Setup, trigger_price: float, trigger_time: int) -> str:
    """Aktif setup için (entry tetiklendi, pozisyon açıldı)."""
    s = setup
    return (
        f"*AKTIF SETUP* {_arrow(s.direction)}\n"
        f"*{s.symbol}* `{s.interval}` — `{s.pattern_name}`\n"
        "\n"
        f"Entry tetiklendi: `{trigger_price:.6g}` @ `{_fmt(trigger_time)}`\n"
        f"SL: `{s.stop:.6g}`  TP1: `{s.tp1:.6g}`  TP2: `{s.tp2:.6g}`"
    )


def exit_card(setup: Setup, outcome: str, exit_price: float, exit_time: int) -> str:
    """Çıkış kartı: TP / STOP / Zamansal İptal / Entry Olmadı."""
    s = setup
    badge_map = {
        "TP":   "✅ *TP*",
        "STOP": "❌ *STOP*",
        "ZI":   "⏱ *ZAMANSAL İPTAL*",
        "EO":   "⚪ *ENTRY OLMADI*",
    }
    badge = badge_map.get(outcome, outcome)
    if outcome in ("TP", "STOP"):
        pct = _abs_pct(exit_price, s.entry)
        sign = "+" if (outcome == "TP") else "-"
        outcome_line = f"{badge}  ({sign}{pct:.2f}%)"
    else:
        outcome_line = badge
    return (
        f"{outcome_line}  {_arrow(s.direction)}\n"
        f"*{s.symbol}* `{s.interval}` — `{s.pattern_name}`\n"
        f"Çıkış: `{exit_price:.6g}` @ `{_fmt(exit_time)}`"
    )
