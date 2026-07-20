"""Bar-by-bar backtest engine for the S/R bounce strategy.

Order of evaluation per bar t (all information available at close of t):
  1. Manage open trade against bar t's high/low (SL first if both hit — conservative).
  2. Update zones with swings confirmed at t.
  3. If flat: check if bar t touched an active zone AND printed a reversal candle.
     Entry is at next bar's open (t+1) — no same-bar fill.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .signals import confirm, trend_direction
from .zones import ZoneTracker


@dataclass
class Trade:
    entry_bar: int
    entry_time: pd.Timestamp
    direction: str
    entry: float
    sl: float
    tp: float
    size: float
    zone_center: float
    pattern: str
    exit_bar: int = -1
    exit_time: pd.Timestamp | None = None
    exit_price: float = np.nan
    exit_reason: str = ""
    pnl: float = np.nan
    r_multiple: float = np.nan


def evaluate_exit(df: pd.DataFrame, t: int, trade: Trade, s: dict) -> tuple[float, str] | None:
    """Bar t's high/low against an open trade's SL/TP (SL checked before TP if
    both hit — conservative), else time exit. Returns (raw_exit_price, reason)
    or None. `raw_exit_price` has no slippage applied yet."""
    h, l, c = df["high"].iloc[t], df["low"].iloc[t], df["close"].iloc[t]
    if trade.direction == "long":
        if l <= trade.sl:
            return trade.sl, "sl"
        if h >= trade.tp:
            return trade.tp, "tp"
    else:
        if h >= trade.sl:
            return trade.sl, "sl"
        if l <= trade.tp:
            return trade.tp, "tp"
    if t - trade.entry_bar >= s["time_exit_bars"]:
        return c, "time"
    return None


def evaluate_setup(df: pd.DataFrame, t: int, zt: ZoneTracker, trend: pd.Series,
                    s: dict) -> dict | None:
    """Bar t (already fed through zt.update(t)) against active zones + reversal
    candle confirmation. Returns a pending-entry dict or None. Caller is
    responsible for the actual fill (backtest fills at t+1 open; a live caller
    may fill at the current price instead)."""
    atr_t = zt.atr[t]
    if not (np.isfinite(atr_t) and atr_t > 0):
        return None
    h, l, c = df["high"].iloc[t], df["low"].iloc[t], df["close"].iloc[t]
    for z in zt.active():
        if z.kind == "support" and l <= z.hi and c > z.hi * 0.999:
            if trend.iloc[t] < 0:
                continue
            pat = confirm(df, t, "long", s["confirm_patterns"])
            if pat:
                sl_px = z.lo - s["sl_atr_mult"] * atr_t
                risk_d = c - sl_px
                return {"direction": "long", "sl": sl_px,
                        "tp": c + s["rr_target"] * risk_d,
                        "zone_center": z.center, "pattern": pat}
        if z.kind == "resistance" and h >= z.lo and c < z.lo * 1.001:
            if s.get("long_only"):
                continue
            if trend.iloc[t] > 0:
                continue
            pat = confirm(df, t, "short", s["confirm_patterns"])
            if pat:
                sl_px = z.hi + s["sl_atr_mult"] * atr_t
                risk_d = sl_px - c
                return {"direction": "short", "sl": sl_px,
                        "tp": c - s["rr_target"] * risk_d,
                        "zone_center": z.center, "pattern": pat}
    return None


def run_backtest(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.Series]:
    s = cfg["strategy"]
    r = cfg["risk"]
    zt = ZoneTracker(df, s["swing_lookback"], s["zone_atr_mult"],
                     s["zone_max_age_bars"], s["min_touches"])
    trend = trend_direction(df, s.get("trend_filter"))
    fee = r["fee_pct"] / 100
    slip = r["slippage_pct"] / 100

    equity = r["initial_equity"]
    eq_curve = np.full(len(df), np.nan)
    trades: list[Trade] = []
    open_trade: Trade | None = None
    pending: dict | None = None

    o = df["open"].values

    for t in range(1, len(df)):
        # 1. fill pending entry at this bar's open
        if pending is not None and open_trade is None:
            px = o[t] * (1 + slip) if pending["direction"] == "long" else o[t] * (1 - slip)
            risk_dist = abs(px - pending["sl"])
            if risk_dist > 0:
                risk_amt = equity * r["risk_pct"] / 100
                size = risk_amt / risk_dist
                equity -= px * size * fee
                open_trade = Trade(t, df.index[t], pending["direction"], px,
                                   pending["sl"], pending["tp"], size,
                                   pending["zone_center"], pending["pattern"])
            pending = None

        # 2. manage open trade against bar t
        if open_trade is not None:
            tr = open_trade
            result = evaluate_exit(df, t, tr, s)
            if result is not None:
                raw_exit_px, reason = result
                exit_px = raw_exit_px * (1 - slip) if tr.direction == "long" else raw_exit_px * (1 + slip)
                gross = (exit_px - tr.entry) * tr.size if tr.direction == "long" \
                    else (tr.entry - exit_px) * tr.size
                equity += gross - exit_px * tr.size * fee
                tr.exit_bar, tr.exit_time = t, df.index[t]
                tr.exit_price, tr.exit_reason = exit_px, reason
                tr.pnl = gross
                tr.r_multiple = gross / (abs(tr.entry - tr.sl) * tr.size)
                trades.append(tr)
                open_trade = None

        # 3. update zones (swings confirmed at t)
        zt.update(t)

        # 4. look for new setup at close of bar t
        if open_trade is None and pending is None:
            pending = evaluate_setup(df, t, zt, trend, s)
        eq_curve[t] = equity

    tdf = pd.DataFrame([vars(x) for x in trades])
    eq = pd.Series(eq_curve, index=df.index).ffill().fillna(r["initial_equity"])
    return tdf, eq


def metrics(tdf: pd.DataFrame, eq: pd.Series, initial: float) -> dict:
    if tdf.empty:
        return {"trades": 0}
    wins = tdf[tdf.pnl > 0]
    losses = tdf[tdf.pnl <= 0]
    gross_win = wins.pnl.sum()
    gross_loss = -losses.pnl.sum()
    dd = (eq / eq.cummax() - 1).min()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    out = {
        "trades": len(tdf),
        "trades_per_month": round(len(tdf) / (years * 12), 2),
        "win_rate": round(len(wins) / len(tdf) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_r": round(tdf.r_multiple.mean(), 2),
        "net_pnl": round(tdf.pnl.sum(), 2),
        "return_pct": round((eq.iloc[-1] / initial - 1) * 100, 1),
        "max_dd_pct": round(dd * 100, 1),
        "long_pf": _side_pf(tdf, "long"),
        "short_pf": _side_pf(tdf, "short"),
        "long_trades": int((tdf.direction == "long").sum()),
        "short_trades": int((tdf.direction == "short").sum()),
    }
    return out


def _side_pf(tdf: pd.DataFrame, side: str) -> float:
    s = tdf[tdf.direction == side]
    if s.empty:
        return float("nan")
    gw = s[s.pnl > 0].pnl.sum()
    gl = -s[s.pnl <= 0].pnl.sum()
    return round(gw / gl, 2) if gl > 0 else float("inf")
