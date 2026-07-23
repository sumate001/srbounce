"""Render the zones the bot is actually stalking — nearest support + nearest
resistance — as a candlestick PNG, windowed from each zone's FIRST touch so the
1-2-3 touch count is visible on the chart."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

BG = "#0F1722"
PANEL = "#16202D"
INK = "#E8EEF4"
MUTED = "#93A3B4"
GRID = "#243244"
UP = "#34C08B"
DOWN = "#E15A6B"
SUP = "#34C08B"
RES = "#E15A6B"
ACC = "#E8B54A"


def pick_nearest_zones(zones, last_price: float):
    """Nearest active support below price + nearest resistance above."""
    sups = [z for z in zones if z.kind == "support" and z.center <= last_price]
    ress = [z for z in zones if z.kind == "resistance" and z.center >= last_price]
    out = []
    if sups:
        out.append(max(sups, key=lambda z: z.center))
    if ress:
        out.append(min(ress, key=lambda z: z.center))
    return out


def render_zones_png(df: pd.DataFrame, zones, market: str, timeframe: str) -> bytes:
    """df: full closed-candle history the tracker was seeded on.
    zones: Zone objects (need .lo/.hi/.center/.kind/.touches/.touch_bars)."""
    first_touch = min(z.touch_bars[0] for z in zones)
    start = max(first_touch - 5, 0)
    win = df.iloc[start:]
    n = len(win)

    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=140)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    for i, (_, row) in zip(range(n), win.iterrows()):
        up = row["close"] >= row["open"]
        color = UP if up else DOWN
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8, zorder=3)
        body_lo, body_hi = sorted((row["open"], row["close"]))
        ax.add_patch(plt.Rectangle((i - 0.33, body_lo), 0.66,
                                   max(body_hi - body_lo, row["high"] * 1e-5),
                                   facecolor=color, edgecolor="none", zorder=3))

    y_lo = min(win["low"].min(), min(z.lo for z in zones))
    y_hi = max(win["high"].max(), max(z.hi for z in zones))
    pad = (y_hi - y_lo) * 0.07
    ax.set_ylim(y_lo - pad, y_hi + pad)

    for z in zones:
        color = SUP if z.kind == "support" else RES
        ax.axhspan(z.lo, z.hi, color=color, alpha=0.16, zorder=1)
        ax.axhline(z.lo, color=color, linewidth=0.7, linestyle="--", alpha=0.6, zorder=2)
        ax.axhline(z.hi, color=color, linewidth=0.7, linestyle="--", alpha=0.6, zorder=2)
        ax.text(n + 1, z.center, f"{z.kind[:3]} {z.center:.0f}\nx{z.touches}",
                color=color, fontsize=9, va="center", fontweight="bold")
        # numbered touch markers at the actual touch candles
        for k, tb in enumerate(z.touch_bars, start=1):
            i = tb - start
            if i < 0 or i >= n:
                continue
            row = win.iloc[i]
            y = row["low"] if z.kind == "support" else row["high"]
            off = -(y_hi - y_lo) * 0.045 if z.kind == "support" else (y_hi - y_lo) * 0.045
            ax.annotate(str(k), (i, y + off), color=BG, fontsize=8, fontweight="bold",
                        ha="center", va="center", zorder=5,
                        bbox=dict(boxstyle="circle,pad=0.25", fc=ACC, ec="none"))

    last = win["close"].iloc[-1]
    ax.axhline(last, color=MUTED, linewidth=0.8, linestyle=":", zorder=2)
    ax.text(n + 1, last, f"now\n{last:.0f}", color=INK, fontsize=8, va="center")

    ax.set_xlim(-1, n + 12)
    ax.grid(color=GRID, linewidth=0.5, alpha=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    step = max(n // 6, 1)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([win.index[i].strftime("%d %b") for i in ticks])
    ax.set_title(f"{market} {timeframe} — nearest S/R zones (since 1st touch)",
                 color=INK, fontsize=11, fontweight="bold", loc="left", pad=10)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
