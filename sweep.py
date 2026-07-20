"""Parameter sweep + walk-forward validation for the S/R bounce strategy.

Usage:
    python sweep.py --market BTCUSDT
    python sweep.py --market ETHUSDT --split 2024-01-01
    python sweep.py --market BTCUSDT --long-only

For each (swing_lookback, zone_atr_mult) combo:
  - run backtest on the in-sample period (before --split)
  - run the SAME params on out-of-sample (after --split)
Outputs:
  results/sweep_<MARKET>.csv        full grid results
  console: in-sample PF heatmap + top-5 params with their OOS performance
"""
import argparse
import copy
import itertools
from pathlib import Path

import pandas as pd
import yaml

from srbounce.data import load_market
from srbounce.engine import metrics, run_backtest

GRID = {
    "swing_lookback": [3, 4, 5, 6, 8],
    "zone_atr_mult": [0.2, 0.3, 0.4, 0.5],
    "min_touches": [2, 3],
}


def run_one(df: pd.DataFrame, cfg: dict) -> dict:
    tdf, eq = run_backtest(df, cfg)
    return metrics(tdf, eq, cfg["risk"]["initial_equity"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--market", required=True)
    ap.add_argument("--split", default="2024-01-01",
                    help="in-sample before this date, out-of-sample after")
    ap.add_argument("--long-only", action="store_true",
                    help="disable short entries (sets trend filter but also drops shorts)")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    mkt = next(m for m in cfg["markets"] if m["name"] == args.market)
    df = load_market(mkt, cfg["data"]["start"], cfg["data"]["cache_dir"])
    split = pd.Timestamp(args.split, tz="UTC")
    ins, oos = df[df.index < split], df[df.index >= split]
    print(f"{args.market}: in-sample {len(ins)} bars, out-of-sample {len(oos)} bars")
    if len(ins) < 500 or len(oos) < 200:
        print("WARNING: one side of the split is very short — results may be unreliable")

    rows = []
    combos = list(itertools.product(*GRID.values()))
    for i, (lb, zm, mt) in enumerate(combos, 1):
        c = copy.deepcopy(cfg)
        c["strategy"].update(swing_lookback=lb, zone_atr_mult=zm, min_touches=mt)
        if args.long_only:
            c["strategy"]["long_only"] = True
        m_in = run_one(ins, c)
        m_oos = run_one(oos, c)
        rows.append({
            "swing_lookback": lb, "zone_atr_mult": zm, "min_touches": mt,
            "in_trades": m_in.get("trades", 0),
            "in_pf": m_in.get("profit_factor"),
            "in_ret": m_in.get("return_pct"),
            "in_dd": m_in.get("max_dd_pct"),
            "oos_trades": m_oos.get("trades", 0),
            "oos_pf": m_oos.get("profit_factor"),
            "oos_ret": m_oos.get("return_pct"),
            "oos_dd": m_oos.get("max_dd_pct"),
        })
        print(f"  [{i}/{len(combos)}] lb={lb} zm={zm} mt={mt} "
              f"IS pf={m_in.get('profit_factor')} ({m_in.get('trades',0)}t) | "
              f"OOS pf={m_oos.get('profit_factor')} ({m_oos.get('trades',0)}t)")

    res = pd.DataFrame(rows)
    out = Path("results")
    out.mkdir(exist_ok=True)
    suffix = "_long" if args.long_only else ""
    res.to_csv(out / f"sweep_{args.market}{suffix}.csv", index=False)

    print("\n=== In-sample PF heatmap (rows=swing_lookback, cols=zone_atr_mult, min_touches=2) ===")
    pv = res[res.min_touches == 2].pivot(index="swing_lookback", columns="zone_atr_mult", values="in_pf")
    print(pv.to_string())

    print("\n=== Top 5 by in-sample PF (min 30 trades) — with their OOS results ===")
    top = res[res.in_trades >= 30].sort_values("in_pf", ascending=False).head(5)
    print(top.to_string(index=False))

    print("\n=== Robustness check ===")
    ok = res[(res.in_trades >= 30)]
    if not ok.empty:
        frac = (ok.in_pf > 1.0).mean() * 100
        oos_frac = (ok[ok.oos_trades >= 10].oos_pf > 1.0).mean() * 100 if (ok.oos_trades >= 10).any() else float("nan")
        print(f"combos with in-sample PF > 1.0: {frac:.0f}%  |  "
              f"of those tested OOS (>=10 trades), PF > 1.0: {oos_frac:.0f}%")
        print("Interpretation: broad profitability across the grid = real edge; "
              "only isolated hot spots = likely overfit.")


if __name__ == "__main__":
    main()
