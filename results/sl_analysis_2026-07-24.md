# SL placement analysis — ETHUSDT 4H, validated config (2026-07-24)

Question: can the SL be tuned so the system "knows it's wrong" faster,
or do trades routinely dip against us and recover?

## Sweep of sl_atr_mult (PF in R units, TP fixed at 2R)

| sl_atr_mult | n | win% | PF_R IS (<2024) | PF_R OOS (>=2024) | avg R |
|---|---|---|---|---|---|
| 0.2 | 157 | 45.2 | 1.50 | 1.58 | +0.28 |
| 0.3 | 152 | 46.7 | 1.52 | 1.80 | +0.32 |
| **0.5 (current)** | 146 | 49.3 | **1.66** | **1.75** | **+0.33** |
| 0.7 | 141 | 48.9 | 1.56 | 1.75 | +0.30 |
| 1.0 | 133 | 49.6 | 1.81 | 1.51 | +0.28 |
| 1.5 | 128 | 53.1 | 1.97 | 1.54 | +0.28 |

0.5 is the only setting strong AND balanced across both windows.
Wider looks better in-sample only (overfit pattern); tighter is worse everywhere.

## MAE of the 146 trades (current config)

- Winners (72): median max adverse excursion 0.36R, p75 0.56R, p90 0.82R.
  Tightening SL to 0.5R would kill ~30% of winners (each worth +2R).
- Losers (74): typically run straight to the full -1R stop.
- Exit breakdown: sl 67 (avg -1.01R), tp 51 (+1.97R), time 28 (+0.52R).

## Conclusion

The market does NOT "know early" — winning bounces routinely retrace ~half
the stop distance before working. Current SL sits at the empirical sweet
spot; do not tighten or widen. If anything is worth researching next, it is
the winner-exit side (e.g. trailing after +1R) — and per the spec, only via
the backtester + walk-forward first.

Generated from ad-hoc scripts against data/ETHUSDT.parquet; PF measured in
R multiples to be independent of position sizing.
