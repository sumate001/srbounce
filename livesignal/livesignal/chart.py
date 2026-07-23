"""Render a candlestick chart with S/R zone bands as a PNG for Telegram."""
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


def render_zones_png(df: pd.DataFrame, zones: list[dict], market: str,
                     timeframe: str) -> bytes:
    """df: OHLC indexed by timestamp (last ~100 closed candles)."""
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=140)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    n = len(df)
    x = range(n)
    for i, (_, row) in zip(x, df.iterrows()):
        up = row["close"] >= row["open"]
        color = UP if up else DOWN
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8, zorder=3)
        body_lo, body_hi = sorted((row["open"], row["close"]))
        ax.add_patch(plt.Rectangle((i - 0.33, body_lo), 0.66,
                                   max(body_hi - body_lo, row["high"] * 1e-5),
                                   facecolor=color, edgecolor="none", zorder=3))

    # lock the y-axis to the candles; zones outside the visible price range
    # would otherwise stretch the axis and squash the chart into noise
    y_lo = df["low"].min()
    y_hi = df["high"].max()
    pad = (y_hi - y_lo) * 0.06
    y_lo, y_hi = y_lo - pad, y_hi + pad

    visible = [z for z in zones if z["hi"] >= y_lo and z["lo"] <= y_hi]
    for z in visible:
        color = SUP if z["kind"] == "support" else RES
        ax.axhspan(z["lo"], z["hi"], color=color, alpha=0.14, zorder=1)
        ax.axhline(z["lo"], color=color, linewidth=0.7, linestyle="--", alpha=0.6, zorder=2)
        ax.axhline(z["hi"], color=color, linewidth=0.7, linestyle="--", alpha=0.6, zorder=2)
        ax.text(n + 1, z["center"], f"{z['kind'][:3]} {z['center']:.0f} x{z['touches']}",
                color=color, fontsize=8, va="center", fontweight="bold")

    last = df["close"].iloc[-1]
    ax.axhline(last, color=MUTED, linewidth=0.8, linestyle=":", zorder=2)
    ax.text(n + 1, last, f"{last:.0f}", color=INK, fontsize=8, va="center")

    ax.set_xlim(-1, n + 14)
    ax.set_ylim(y_lo, y_hi)
    ax.grid(color=GRID, linewidth=0.5, alpha=0.6)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    step = max(n // 6, 1)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime("%d %b") for i in ticks])
    ax.set_title(f"{market} {timeframe} — active S/R zones",
                 color=INK, fontsize=11, fontweight="bold", loc="left", pad=10)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
