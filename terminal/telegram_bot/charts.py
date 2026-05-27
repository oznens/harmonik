"""Setup için chart PNG üreteci.

Açık tema (beyaz arkaplan + altın aksent), X/A/B/C/D etiketli pivot daireleri,
kesik bağlantı çizgileri, XABCD üçgen dolguları, PRZ (D bölgesi) kutusu,
üstte koyu başlık bandı.
"""
from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Polygon, Rectangle

from terminal.detection.models import Setup
from terminal.detection.pivots import find_pivots, Pivot
from terminal.detection.potential import find_potential_patterns
from terminal.detection.scanner import default_threshold

# Renk paleti
BG_HEADER = "#0e0e10"
TXT_GOLD = "#d4a72c"
TXT_SUB = "#9a9a9a"
GREEN = "#26a69a"
RED = "#ef5350"
PIVOT_CIRCLE_FACE = "#ffffff"
PIVOT_CIRCLE_EDGE = "#222222"
DASH = "#666666"
TRIANGLE_FILL = "#fef5e0"   # Çok açık bej (XABCD üçgen dolguları)
TRIANGLE_EDGE = "#d4a72c"
PRZ_FILL = "#e8c97a"
PRZ_EDGE = "#b8860b"
ENTRY_COLOR = "#0288d1"
SL_COLOR = "#ef5350"
TP_COLOR = "#26a69a"


def _klines_to_df(klines: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(klines)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    return df[["Open", "High", "Low", "Close", "Volume"]]


def render_setup_chart(setup: Setup, klines: list[dict[str, Any]]) -> bytes:
    """Açık temalı setup chart'ı: X-A-B-C-D etiketli + XABCD üçgenleri + PRZ kutusu."""
    # Zoom: X pivot'undan 10 bar önce → dataset sonu (pattern görünür olsun)
    df_full = _klines_to_df(klines)
    x_t = pd.to_datetime(setup.pivots["X"].time, unit="ms", utc=True)
    if x_t in df_full.index:
        x_full_idx = df_full.index.get_loc(x_t)
        pad_left = max(0, x_full_idx - 10)
        df = df_full.iloc[pad_left:].copy()
    else:
        df = df_full

    # Pivot zaman/fiyat/index
    pivot_data: dict[str, tuple[int, float]] = {}
    for letter in "XABCD":
        p = setup.pivots[letter]
        t = pd.to_datetime(p.time, unit="ms", utc=True)
        if t in df.index:
            pivot_data[letter] = (df.index.get_loc(t), p.price)

    # Açık tema mplfinance
    mc = mpf.make_marketcolors(
        up=GREEN, down=RED, edge="inherit", wick="inherit",
        volume="in", inherit=True,
    )
    style = mpf.make_mpf_style(
        base_mpf_style="classic",
        marketcolors=mc,
        gridcolor="#eeeeee",
        gridstyle="-",
        facecolor="#ffffff",
        edgecolor="#cccccc",
        figcolor="#ffffff",
        rc={
            "font.size": 10,
            "axes.labelcolor": "#333",
            "axes.edgecolor": "#cccccc",
            "xtick.color": "#666",
            "ytick.color": "#666",
        },
    )

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        volume=False,
        figsize=(15, 7.5),
        returnfig=True,
        tight_layout=False,
        warn_too_much_data=10_000,
        update_width_config={"candle_width": 0.7, "candle_linewidth": 1.0},
    )
    ax = axes[0]

    # 1) XABCD üçgen dolguları — yön bazlı renk (bull=yeşil, bear=kırmızı tonu)
    if all(k in pivot_data for k in "XABCD"):
        x = pivot_data["X"]; a = pivot_data["A"]; b = pivot_data["B"]
        c = pivot_data["C"]; d = pivot_data["D"]
        # Pattern yönüne göre saydam renk — TradingView Bullish/Bearish Bat tarzı
        if setup.direction == "bull":
            tri_fill = "#cde9d9"  # açık yeşil
            tri_edge = "#26a69a"
        else:
            tri_fill = "#f5cdcd"  # açık kırmızı
            tri_edge = "#ef5350"
        # Üçgen 1: X - A - B
        tri1 = Polygon(
            [x, a, b],
            facecolor=tri_fill, edgecolor=tri_edge,
            alpha=0.55, linewidth=0.8, zorder=2,
        )
        ax.add_patch(tri1)
        # Üçgen 2: B - C - D
        tri2 = Polygon(
            [b, c, d],
            facecolor=tri_fill, edgecolor=tri_edge,
            alpha=0.55, linewidth=0.8, zorder=2,
        )
        ax.add_patch(tri2)

    # 2) X-A-B-C-D bağlantı çizgileri (kesik, üçgenlerin kenarları)
    letters = "XABCD"
    for i in range(len(letters) - 1):
        if letters[i] in pivot_data and letters[i + 1] in pivot_data:
            a_pt = pivot_data[letters[i]]
            b_pt = pivot_data[letters[i + 1]]
            ax.plot([a_pt[0], b_pt[0]], [a_pt[1], b_pt[1]],
                    linestyle="--", color=DASH, linewidth=1.4, zorder=5)

    # 3) Pivot daireleri — küçük, sade etiketli
    for letter, (x_idx, price) in pivot_data.items():
        ax.scatter([x_idx], [price], s=320, color=PIVOT_CIRCLE_FACE,
                   edgecolor=PIVOT_CIRCLE_EDGE, linewidth=1.2, zorder=10)
        ax.text(x_idx, price, letter, ha="center", va="center",
                fontsize=9, fontweight="bold", color="#000", zorder=11)

    # 4) PRZ ("D bölgesi") kutusu — sağ üstte, B noktasından sağa
    if "D" in pivot_data:
        d_idx_x = pivot_data["D"][0]
        # Sol kenar: B noktasından başla (XABCD'nin orta noktasından sonra)
        if "B" in pivot_data:
            left_edge = pivot_data["B"][0] + 2
        else:
            left_edge = max(0, d_idx_x - 30)
        right_edge = min(len(df) - 1, d_idx_x + 6)
        width = right_edge - left_edge
        rect = Rectangle(
            (left_edge, setup.prz_low), width, setup.prz_high - setup.prz_low,
            facecolor=PRZ_FILL, edgecolor=PRZ_EDGE,
            linewidth=1.2, alpha=0.6, zorder=4,
        )
        ax.add_patch(rect)
        # D? etiketi (PRZ kutusunun sağ üst köşesi)
        ax.text(right_edge - 0.5, setup.prz_high, "D?",
                ha="right", va="bottom", fontsize=10, fontweight="bold",
                color=PRZ_EDGE, zorder=12)

    # 5) Entry / SL / TP1 / TP2 yatay çizgileri — net + etiketli
    levels = [
        ("Entry", setup.entry, ENTRY_COLOR, "-",  1.4),
        ("SL",    setup.stop,  SL_COLOR,    "--", 1.2),
        ("TP1",   setup.tp1,   TP_COLOR,    "--", 1.2),
        ("TP2",   setup.tp2,   TP_COLOR,    ":",  1.0),
    ]
    x_right = len(df) - 1
    for label, price, color, ls, lw in levels:
        ax.axhline(price, color=color, linewidth=lw,
                   linestyle=ls, alpha=0.85, zorder=3)
        # Sağ tarafa renkli etiket kutusu
        ax.annotate(
            f" {label}  {price:.6g} ",
            xy=(x_right, price),
            xytext=(8, 0), textcoords="offset points",
            ha="left", va="center",
            fontsize=9, fontweight="bold",
            color="#ffffff",
            bbox=dict(
                boxstyle="round,pad=0.25",
                facecolor=color, edgecolor="none",
                alpha=0.92,
            ),
            zorder=20,
            clip_on=False,
        )

    # 6) Başlık (üstte koyu band)
    direction_text = "Bearish" if setup.direction == "bear" else "Bullish"
    title = f"terminalMiraz / {setup.symbol} {setup.interval} / {direction_text} {setup.pattern_name}"
    subtitle_parts = [f"D bölgesi: {setup.prz_low:.6g} - {setup.prz_high:.6g}"]
    if setup.q_score:
        subtitle_parts.append(f"Q {setup.q_score} {setup.q_category}")
    if setup.ab_cd_equivalent:
        subtitle_parts.append("AB=CD ✓")
    subtitle = "   ·   ".join(subtitle_parts)

    # Header band üstte
    fig.patch.set_facecolor("#ffffff")
    header_h = 0.075
    fig.subplots_adjust(top=1 - header_h - 0.02)
    header_ax = fig.add_axes([0, 1 - header_h, 1, header_h])
    header_ax.set_facecolor(BG_HEADER)
    header_ax.set_xticks([])
    header_ax.set_yticks([])
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    header_ax.text(0.012, 0.68, title, color=TXT_GOLD,
                   fontsize=15, fontweight="bold", va="center", ha="left")
    header_ax.text(0.012, 0.25, subtitle, color=TXT_SUB,
                   fontsize=10, va="center", ha="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches=None,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()



def render_potential_chart(
    symbol: str,
    interval: str,
    klines: list[dict[str, Any]],
    zigzag_threshold: float | None = None,
) -> bytes | None:
    """Henüz oluşmamış (D pivot yok) potansiyel pattern chart'ı.

    Son 4 pivot (X-A-B-C) varsa, her spec için potansiyel D bölgesini sarı
    kutu olarak çizer. "Fiyat D bölgesine girerse Bullish Gartley olur"
    tipi öngörü sağlar (TradingView'de manuel çizilen olası dönüş gibi).

    Returns None if no potential pattern (return early).
    """
    threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
    pivots = find_pivots(klines, threshold)
    if len(pivots) < 4:
        return None
    # Sadece son 4 pivot — en güncel potansiyel pattern
    last4 = pivots[-4:]
    matches = find_potential_patterns(last4)
    if not matches:
        return None
    # Birden fazla varsa en yüksek d_ideal yakın olanı al (en spesifik)
    match = matches[0]

    # Zoom: X pivot'undan biraz öncesi → bar dizisi sonu (~%20 padding sağa)
    df_full = _klines_to_df(klines)
    x_t = pd.to_datetime(match.x.time, unit="ms", utc=True)
    if x_t in df_full.index:
        x_full_idx = df_full.index.get_loc(x_t)
        # X'ten önce 10 bar pad, sonra dataset sonu + sağa boşluk yok (D? kutusu için bar üretmiyoruz)
        pad_left = max(0, x_full_idx - 10)
        df = df_full.iloc[pad_left:].copy()
    else:
        df = df_full
    pivot_data: dict[str, tuple[int, float]] = {}
    for letter, piv in (("X", match.x), ("A", match.a), ("B", match.b), ("C", match.c)):
        t = pd.to_datetime(piv.time, unit="ms", utc=True)
        if t in df.index:
            pivot_data[letter] = (df.index.get_loc(t), piv.price)

    mc = mpf.make_marketcolors(up=GREEN, down=RED, edge="inherit", wick="inherit",
                                volume="in", inherit=True)
    style = mpf.make_mpf_style(
        base_mpf_style="classic", marketcolors=mc,
        gridcolor="#eeeeee", gridstyle="-",
        facecolor="#ffffff", edgecolor="#cccccc", figcolor="#ffffff",
        rc={"font.size": 10, "axes.labelcolor": "#333",
            "axes.edgecolor": "#cccccc", "xtick.color": "#666", "ytick.color": "#666"},
    )
    fig, axes = mpf.plot(
        df, type="candle", style=style, volume=False, figsize=(15, 7.5),
        returnfig=True, tight_layout=False, warn_too_much_data=10_000,
        update_width_config={"candle_width": 0.7, "candle_linewidth": 1.0},
    )
    ax = axes[0]

    # X-A-B-C üçgenleri (yön bazlı renk)
    if all(k in pivot_data for k in "XABC"):
        x = pivot_data["X"]; a = pivot_data["A"]; b = pivot_data["B"]; c = pivot_data["C"]
        if match.direction == "bull":
            tri_fill, tri_edge = "#cde9d9", "#26a69a"
        else:
            tri_fill, tri_edge = "#f5cdcd", "#ef5350"
        # Üçgen X-A-B
        ax.add_patch(Polygon([x, a, b], facecolor=tri_fill, edgecolor=tri_edge,
                              alpha=0.55, linewidth=0.8, zorder=2))
        # Çizgi B-C
        ax.plot([b[0], c[0]], [b[1], c[1]],
                linestyle="--", color=tri_edge, linewidth=1.4, zorder=3)
        # Tahmini C-D çizgisi (kesik kırmızı, beklenen yön)
        d_x_proj = c[0] + max(5, (c[0] - b[0]))  # C'den ileri tahmini bar sayısı
        ax.plot([c[0], d_x_proj], [c[1], match.d_ideal_price],
                linestyle=":", color=DASH, linewidth=1.2, zorder=3)

    # X-A-B-C bağlantı çizgileri
    letters = "XABC"
    for i in range(len(letters) - 1):
        if letters[i] in pivot_data and letters[i + 1] in pivot_data:
            a_pt = pivot_data[letters[i]]
            b_pt = pivot_data[letters[i + 1]]
            ax.plot([a_pt[0], b_pt[0]], [a_pt[1], b_pt[1]],
                    linestyle="--", color=DASH, linewidth=1.4, zorder=5)

    # Pivot daireleri
    for letter, (xi, price) in pivot_data.items():
        ax.scatter([xi], [price], s=320, color=PIVOT_CIRCLE_FACE,
                   edgecolor=PIVOT_CIRCLE_EDGE, linewidth=1.2, zorder=10)
        ax.text(xi, price, letter, ha="center", va="center",
                fontsize=9, fontweight="bold", color="#000", zorder=11)

    # Potansiyel D bölgesi (sarı kutu)
    c_idx = pivot_data["C"][0] if "C" in pivot_data else len(df) - 30
    right_edge = min(len(df) - 1, c_idx + max(10, c_idx // 4))
    rect = Rectangle(
        (c_idx + 1, match.d_zone_low),
        right_edge - c_idx - 1, match.d_zone_high - match.d_zone_low,
        facecolor=PRZ_FILL, edgecolor=PRZ_EDGE,
        linewidth=1.2, alpha=0.5, zorder=4,
    )
    ax.add_patch(rect)
    ax.text(right_edge - 0.5, match.d_zone_high, "D?",
            ha="right", va="bottom", fontsize=11, fontweight="bold",
            color=PRZ_EDGE, zorder=12)
    # İdeal D fiyat çizgisi
    ax.axhline(match.d_ideal_price, color=PRZ_EDGE, linewidth=1.0,
               linestyle=":", alpha=0.7, zorder=3)
    # D ideal label
    ax.annotate(
        f" D ideal  {match.d_ideal_price:.6g} ",
        xy=(len(df) - 1, match.d_ideal_price),
        xytext=(8, 0), textcoords="offset points",
        ha="left", va="center",
        fontsize=9, fontweight="bold", color="#ffffff",
        bbox=dict(boxstyle="round,pad=0.25",
                  facecolor=PRZ_EDGE, edgecolor="none", alpha=0.92),
        zorder=20, clip_on=False,
    )

    # Başlık
    direction_text = "Bearish" if match.direction == "bear" else "Bullish"
    title = (f"terminalMiraz / {symbol} {interval} / "
             f"POTANSİYEL {direction_text} {match.spec.name}")
    subtitle = (f"D bölgesi: {match.d_zone_low:.6g} - {match.d_zone_high:.6g}   ·   "
                f"B={match.b_ratio:.3f}  C={match.c_ratio:.3f}   ·   "
                f"Fiyat D bölgesine girerse formasyon tamamlanır")

    fig.patch.set_facecolor("#ffffff")
    header_h = 0.075
    fig.subplots_adjust(top=1 - header_h - 0.02)
    header_ax = fig.add_axes([0, 1 - header_h, 1, header_h])
    header_ax.set_facecolor(BG_HEADER)
    header_ax.set_xticks([]); header_ax.set_yticks([])
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    header_ax.text(0.012, 0.68, title, color=TXT_GOLD,
                   fontsize=15, fontweight="bold", va="center", ha="left")
    header_ax.text(0.012, 0.25, subtitle, color=TXT_SUB,
                   fontsize=10, va="center", ha="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches=None,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
