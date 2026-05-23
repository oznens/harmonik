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
    df = _klines_to_df(klines)

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

    # 1) XABCD üçgen dolguları (çok açık bej arka plan)
    if all(k in pivot_data for k in "XABCD"):
        x = pivot_data["X"]; a = pivot_data["A"]; b = pivot_data["B"]
        c = pivot_data["C"]; d = pivot_data["D"]
        # Üçgen 1: X - A - B
        tri1 = Polygon(
            [x, a, b],
            facecolor=TRIANGLE_FILL, edgecolor="none",
            alpha=0.85, zorder=2,
        )
        ax.add_patch(tri1)
        # Üçgen 2: B - C - D
        tri2 = Polygon(
            [b, c, d],
            facecolor=TRIANGLE_FILL, edgecolor="none",
            alpha=0.85, zorder=2,
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

    # 3) Pivot daireleri — büyük, kalın etiketli
    for letter, (x_idx, price) in pivot_data.items():
        ax.scatter([x_idx], [price], s=800, color=PIVOT_CIRCLE_FACE,
                   edgecolor=PIVOT_CIRCLE_EDGE, linewidth=2.0, zorder=10)
        ax.text(x_idx, price, letter, ha="center", va="center",
                fontsize=15, fontweight="bold", color="#000", zorder=11)

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
        ax.text(right_edge - 0.5, setup.prz_high,
                "D?" if setup.direction == "bear" else "D?",
                ha="right", va="bottom", fontsize=13, fontweight="bold",
                color=PRZ_EDGE, zorder=12)

    # 5) Entry / SL / TP yatay çizgileri (sade, transparan)
    ax.axhline(setup.entry, color=ENTRY_COLOR, linewidth=1.0,
               linestyle="-", alpha=0.5, zorder=3)
    ax.axhline(setup.stop, color=SL_COLOR, linewidth=0.9,
               linestyle="--", alpha=0.45, zorder=3)
    ax.axhline(setup.tp1, color=TP_COLOR, linewidth=0.9,
               linestyle="--", alpha=0.45, zorder=3)

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

