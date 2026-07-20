"""Run the S/R bounce backtest across all markets in config.yaml.

Usage:
    python run.py                 # run all markets (uses cache if present)
    python run.py --refresh       # force re-download data
    python run.py --market SPY    # single market
"""
import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from srbounce.data import load_market
from srbounce.engine import metrics, run_backtest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--market", default=None)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    rows = []
    for mkt in cfg["markets"]:
        if args.market and mkt["name"] != args.market:
            continue
        print(f"=== {mkt['name']} ===")
        try:
            df = load_market(mkt, cfg["data"]["start"], cfg["data"]["cache_dir"], args.refresh)
        except Exception as e:
            print(f"  data error: {e}")
            continue
        print(f"  {len(df)} bars  {df.index[0].date()} -> {df.index[-1].date()}")
        tdf, eq = run_backtest(df, cfg)
        m = metrics(tdf, eq, cfg["risk"]["initial_equity"])
        m["market"] = mkt["name"]
        rows.append(m)
        print("  " + json.dumps(m, ensure_ascii=False))
        if not tdf.empty:
            tdf.to_csv(out_dir / f"trades_{mkt['name']}.csv", index=False)
        eq.to_csv(out_dir / f"equity_{mkt['name']}.csv")

    if rows:
        summary = pd.DataFrame(rows).set_index("market")
        summary.to_csv(out_dir / "summary.csv")
        print("\n=== Summary ===")
        print(summary[["trades", "trades_per_month", "win_rate", "profit_factor",
                       "return_pct", "max_dd_pct", "long_pf", "short_pf"]].to_string())


if __name__ == "__main__":
    main()
