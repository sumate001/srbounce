"""Acceptance test: live logic == backtest logic.

Replays historical ETH candles through the SAME decision path the live loop
uses each wake — trailing `history_bars` window, seed_zone_tracker over the
window, evaluate_exit then evaluate_setup on the newest closed bar — and fills
at the next bar's open (the replay equivalent of "current price right after
close"). The resulting trade list must match srbounce.engine.run_backtest on
the same candles.

Usage:
    python tests/replay_parity.py [--bars N] [--data PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from srbounce.engine import Trade, evaluate_exit, evaluate_setup, run_backtest
from srbounce.signals import trend_direction

from livesignal.paper import PaperBroker
from livesignal.trader import seed_zone_tracker


def replay_live_path(df: pd.DataFrame, cfg: dict, window: int, start_t: int) -> pd.DataFrame:
    s, r = cfg["strategy"], cfg["risk"]
    pb = PaperBroker(r["fee_pct"], r["slippage_pct"])
    equity = r["initial_equity"]
    trades: list[dict] = []
    open_trade: dict | None = None
    pending: dict | None = None

    for t in range(start_t, len(df)):
        # fill last wake's signal at this bar's open (live: price right after close)
        if pending is not None and open_trade is None:
            fill = pb.fill_entry(equity, pending["direction"], df["open"].iloc[t],
                                 pending["sl"], r["risk_pct"])
            equity = fill.equity_after
            open_trade = {**pending, "entry": fill.price, "size": fill.size,
                          "entry_bar": t, "entry_time": df.index[t]}
            pending = None

        # exactly what run_market_cycle does on each wake, on the trailing window
        lo = max(0, t + 1 - window)
        win = df.iloc[lo : t + 1]
        wt = len(win) - 1

        if open_trade is not None:
            tr = Trade(entry_bar=wt - (t - open_trade["entry_bar"]),
                       entry_time=open_trade["entry_time"],
                       direction=open_trade["direction"], entry=open_trade["entry"],
                       sl=open_trade["sl"], tp=open_trade["tp"],
                       size=open_trade["size"],
                       zone_center=open_trade["zone_center"],
                       pattern=open_trade["pattern"])
            result = evaluate_exit(win, wt, tr, s)
            if result is not None:
                raw_px, reason = result
                ex = pb.fill_exit(equity, tr.direction, tr.entry, tr.sl, tr.size, raw_px)
                equity = ex.equity_after
                trades.append({**open_trade, "exit_time": df.index[t],
                               "exit_price": ex.price, "exit_reason": reason,
                               "pnl": ex.pnl, "r_multiple": ex.r_multiple})
                open_trade = None

        zt = seed_zone_tracker(win, s)
        trend = trend_direction(win, s.get("trend_filter"))
        if open_trade is None and pending is None:
            pending = evaluate_setup(win, wt, zt, trend, s)

    return pd.DataFrame(trades)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=1500, help="decision bars to replay")
    ap.add_argument("--window", type=int, default=800, help="live history_bars")
    ap.add_argument("--data", default="/home/sumate/data/ETHUSDT.parquet")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    df = pd.read_parquet(args.data)
    start_t = len(df) - args.bars

    bt_trades, _ = run_backtest(df, cfg)
    bt = bt_trades[bt_trades.entry_bar >= start_t].reset_index(drop=True)
    live = replay_live_path(df, cfg, args.window, start_t)

    print(f"replay range: {df.index[start_t]} -> {df.index[-1]}  ({args.bars} bars)")
    print(f"backtest trades: {len(bt)}   live-path trades: {len(live)}")

    ok = True
    n = max(len(bt), len(live))
    for i in range(n):
        if i >= len(bt) or i >= len(live):
            ok = False
            side = "backtest" if i >= len(live) else "live"
            row = (bt if i >= len(live) else live).iloc[i]
            print(f"  MISMATCH extra {side} trade: {row['entry_time']} {row['direction']}")
            continue
        b, l = bt.iloc[i], live.iloc[i]
        # pnl/size depend on the equity path (backtest compounds from 2020;
        # replay starts fresh), so compare price fields + size-independent R.
        # Relative tolerance 1e-4: an old zone whose touches predate the live
        # 800-bar window can have its center shifted at the ~1e-7 level, which
        # propagates into sl/tp — "within rounding" per the acceptance criteria.
        fields_close = (
            all(abs(b[f] - l[f]) <= 1e-4 * abs(b[f]) for f in
                ["entry", "sl", "tp", "exit_price"])
            and abs(b["r_multiple"] - l["r_multiple"]) <= 1e-2
        )
        same = (b.entry_time == l.entry_time and b.direction == l.direction
                and b.exit_reason == l.exit_reason and fields_close)
        if not same:
            ok = False
            print(f"  MISMATCH #{i}:")
            print(f"    backtest: {b.entry_time} {b.direction} e={b.entry:.4f} "
                  f"sl={b.sl:.4f} tp={b.tp:.4f} exit={b.exit_reason}@{b.exit_price:.4f} pnl={b.pnl:.4f}")
            print(f"    live:     {l.entry_time} {l.direction} e={l.entry:.4f} "
                  f"sl={l.sl:.4f} tp={l.tp:.4f} exit={l.exit_reason}@{l.exit_price:.4f} pnl={l.pnl:.4f}")

    if ok:
        print("PARITY OK — live decision path reproduces the backtester exactly.")
        sys.exit(0)
    print("PARITY FAILED")
    sys.exit(1)


if __name__ == "__main__":
    main()
