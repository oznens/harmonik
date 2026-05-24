"""Setup → Telegram mesaj kartı formatlayıcısı (Markdown)."""
from __future__ import annotations

from terminal.detection.models import Setup
from terminal.timeutil import format_local


def _fmt(ms: int) -> str:
    return format_local(ms)


def _arrow(direction: str) -> str:
    return "▲ BULL" if direction == "bull" else "▼ BEAR"


def _abs_pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100 if b else 0.0


def _q_badge(setup: Setup) -> str:
    if not setup.q_score:
        return ""
    return f"Q {setup.q_score} · {setup.q_category or '?'}"


def _htf_line(setup: Setup) -> str:
    if setup.htf_interval is None or setup.htf_trend is None:
        return ""
    arrow = {"bull": "↑", "bear": "↓", "neutral": "→"}.get(setup.htf_trend, "?")
    if setup.htf_aligned is True:
        align = "uyumlu ✓"
    elif setup.htf_aligned is False:
        align = "ZIT ⚠️"
    else:
        align = "nötr"
    return f"HTF ({setup.htf_interval}): {arrow} {setup.htf_trend} — {align}"


def aday_card(setup: Setup, karakter: tuple[float, int] | None = None) -> str:
    """Aday setup için (yeni tespit edildi, henüz fiyat PRZ'ye girmedi).

    Args:
        karakter: opsiyonel (karakter_score, sample_count) — lab verisi varsa.
    """
    s = setup
    d_time = s.pivots["D"].time
    risk_pct = _abs_pct(s.stop, s.entry)
    reward1_pct = _abs_pct(s.tp1, s.entry)
    rr = reward1_pct / risk_pct if risk_pct else 0.0

    header = "*ADAY SETUP*"
    if s.elenen:
        header = "*ADAY [ELENEN]*"
    q = _q_badge(s)
    htf = _htf_line(s)

    lines = [
        f"{header} {_arrow(s.direction)}" + (f"   `{q}`" if q else ""),
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
    ]
    if htf:
        lines.append(htf)
    if karakter is not None and karakter[1] >= 3:
        score, n = karakter
        lines.append(f"Karakter: `{score:.0f}/100` ({n} örneklem)")
    lines.append(f"D pivot: `{_fmt(d_time)}`")
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
    from terminal.karakter.score import trade_r

    s = setup
    badge_map = {
        "TP":   "✅ *TP*",
        "STOP": "❌ *STOP*",
        "ZI":   "⏱ *ZAMANSAL İPTAL*",
        "EO":   "⚪ *ENTRY OLMADI*",
    }
    badge = badge_map.get(outcome, outcome)
    r_value = trade_r(s.entry, s.stop, s.tp1, outcome)
    if outcome in ("TP", "STOP"):
        pct = _abs_pct(exit_price, s.entry)
        sign = "+" if (outcome == "TP") else "-"
        r_sign = "+" if r_value > 0 else ""
        outcome_line = f"{badge}  ({sign}{pct:.2f}% · {r_sign}{r_value:.2f}R)"
    else:
        outcome_line = badge
    return (
        f"{outcome_line}  {_arrow(s.direction)}\n"
        f"*{s.symbol}* `{s.interval}` — `{s.pattern_name}`\n"
        f"Çıkış: `{exit_price:.6g}` @ `{_fmt(exit_time)}`"
    )
