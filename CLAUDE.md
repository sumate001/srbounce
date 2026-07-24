# livesignal — full-auto S/R bounce trading service

## Purpose

A standalone service that trades the **S/R bounce reversal** strategy on ETH/USDT
fully automatically, and sends Telegram notifications for every event (no manual
confirmation step). It reuses the exact strategy code already validated in the
`srbounce` backtester so that live behaviour matches backtested results.

This spec is the source of truth. STATUS: BUILT and running (paper phase since
2026-07-24). It lives as the `livesignal/` directory of the srbounce monorepo at
`https://github.com/sumate001/srbounce` (the original plan of a separate repo on
the local GitLab was dropped — merged by user decision). Do not re-derive
strategy logic — import it from `srbounce`.

## Non-negotiable principle: live logic == backtest logic

The zone detection and candle confirmation MUST be the exact same code paths as
the backtester (`srbounce/zones.py` `ZoneTracker`, `srbounce/signals.py`
`confirm`). If live logic diverges from backtest logic even slightly, every
validated metric (PF, walk-forward results) becomes meaningless. Import these
modules directly; do not copy-paste or reimplement.

Package `srbounce` as an installable dependency (add `pyproject.toml` / `setup.py`
to the srbounce project, or vendor it as a git submodule) so `livesignal` can
`from srbounce.zones import ZoneTracker`.

## Validated configuration (do not change without re-running the sweep)

These parameters were selected from a 40-combo parameter sweep with walk-forward
validation (in-sample before 2024-01-01, out-of-sample after). They were chosen
for *stability across the grid*, not peak in-sample PF.

```yaml
market: ETH/USDT
exchange: binance
timeframe: 4h
swing_lookback: 4
zone_atr_mult: 0.3
min_touches: 3
zone_max_age_bars: 500
confirm_patterns: [pin, engulfing]
sl_atr_mult: 0.5          # SL placed beyond zone edge by this * ATR(14)
rr_target: 2.0            # TP = entry +/- (risk_distance * rr_target)
time_exit_bars: 40        # close if neither SL nor TP hit
trend_filter: ema200      # REQUIRED — the validated numbers were produced WITH this
                          # filter. An earlier version of this spec said "null / both
                          # sides"; that was wrong (backtests IS PF 0.95). Verified by
                          # results/sweep_2026-07-24.csv.
risk_pct: 11              # HALF-KELLY, user's explicit choice (2026-07-24).
                          # Full Kelly ≈ 22% measured from the validated config's
                          # 146-trade R distribution. Used together with the
                          # bank-the-profit scheme below.
fee_pct: 0.1              # Binance spot taker, per side
slippage_pct: 0.02
daily_loss_limit_pct: 12  # one full SL loss trips it for the rest of the UTC day
```

Reference backtest result for this config (fee 0.1%/side, re-validated
2026-07-24 on current data — see `results/sweep_2026-07-24.csv`):
IS PF 1.65 / OOS PF 1.76, ~1.9 trades/month, win 49.3%, avg +0.33R.
An earlier claim of OOS 1.81 came from the same config on shorter data.
SL width was separately validated (see `results/sl_analysis_2026-07-24.md`):
0.5 ATR is the sweet spot — do not tighten or widen it.

## Money model: half-Kelly + bank-the-profit (user's chosen scheme)

The pot is capped at `initial_equity` (1000). After every closed trade, any
equity above the cap moves to a `banked` column in the `state` table and is
NEVER risked again. Losses shrink the pot (position sizes shrink with it);
there is no topping-up. Expected profile from Monte Carlo (20k shuffles of the
146-trade R sequence): median total ~6.5x over ~6.5y, ~0% chance of net loss
over a full series, but the pot WILL dip below 50% of the cap along the way —
this is accepted by design. `/status` and trade-closed messages show `pot` and
`banked` separately.

BTC/USDT runs in **signal-only mode**: detect and log/notify setups, but never
open trades. BTC's edge is regime-dependent (profitable OOS both-sides, but not
stable across both time windows) so it stays observational until it earns a live
track record.

## Take-profit rule (explicit)

TP is a **fixed reward:risk multiple of 2.0**, computed at entry:

```
risk_distance = abs(entry_price - stop_loss)
long:  take_profit = entry_price + rr_target * risk_distance
short: take_profit = entry_price - rr_target * risk_distance
```

This exact rule produced the validated PF. Do NOT substitute trailing stops,
opposite-zone targets, or partial exits in v1 — those change the strategy's
statistical profile and would invalidate the backtest. They can be added later
ONLY by first adding them to the srbounce backtester and re-running the sweep to
compare.

## Execution model

- **Phase 1 (default): paper trading.** A `paper: true` flag. On a signal the
  service records a simulated trade against a local paper-equity balance and
  tracks SL/TP/time-exit against real incoming prices. No exchange orders placed.
- **Phase 2: live.** Flip `paper: false`. Same signal path, but submit real
  market orders via ccxt to Binance. This is a config flip only — the decision
  logic is identical, which is the whole point of the paper phase.

Run paper for ~2–3 months (≈5–8 signals) and compare the realised trade log
against the backtest distribution before ever flipping to live.

## Signal loop

1. Sleep until the next 4H candle **close** (Binance UTC candle boundaries:
   00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC). Wake shortly after close.
2. Fetch recent OHLC via ccxt (`fetch_ohlcv`, enough history to seed ATR + zones,
   e.g. last 800 candles).
3. Feed candles into `ZoneTracker` walk-forward exactly as the backtester does —
   the newest **closed** candle is the decision bar. Never act on the forming
   (incomplete) candle.
4. If flat and the decision bar touched an active zone AND printed a valid
   reversal candle (`confirm`), compute entry (next candle open — in live, the
   current price right after close is the practical fill), SL, TP, size.
5. Open the trade (paper or live) and send a Telegram "trade opened" message.
6. On every wake, first manage the open trade against the latest candle's
   high/low: SL checked before TP if both are touched in one candle
   (conservative, matches backtest). Apply time exit at `time_exit_bars`.
7. Never hold more than one position per market at a time.

## Risk controls / kill switch

- **Daily loss limit:** if cumulative realised loss for the current UTC day
  exceeds `2%` of equity, stop opening new trades until the next day. Managing
  existing open trades continues.
- **`/pause` / `/resume`** Telegram commands: `/pause` stops new entries
  immediately (open trades still managed); `/resume` re-enables.
- On startup, load persisted state (open trade, equity, paused flag) from SQLite
  so a restart never loses or double-counts a position.
- Fail safe: on any unhandled exception in the loop, do NOT open trades — log,
  notify via Telegram, and continue managing existing positions.

## Telegram notifications

Notify (not confirm) on:
- **Trade opened** — market, direction, entry, SL, TP, risk %, size, the zone
  center that triggered it, and the confirming candle pattern.
- **Trade closed** — exit reason (sl/tp/time), exit price, P/L in quote + R
  multiple, updated equity.
- **BTC signal-only** — "would have entered" alerts, tagged clearly as
  observational.
- **Weekly summary** — trades, win rate, net P/L, current open position.
- **System** — startup, pause/resume, daily-loss-limit tripped, errors.

Commands: `/status` (pot, banked, open position, today's P/L, paused?),
`/zones` (rendered candlestick chart image: nearest support + resistance only,
windowed from each zone's first touch, numbered touch markers; text fallback
on render failure), `/pause`, `/resume`. Unknown commands get a help reply.

Bot token + chat_id come from `.env` (see below). Messages are HTML-formatted
(bold headers, emoji, <pre> number blocks) with plain-text fallback; no confirm
buttons are needed in the full-auto model.

## Persistence (SQLite)

Tables:
- `trades` — id, market, direction, entry_time, entry, sl, tp, size,
  zone_center, pattern, exit_time, exit_price, exit_reason, pnl, r_multiple,
  paper (bool). Mirror the backtester's Trade fields so logs are directly
  comparable to backtest output.
- `state` — singleton row: equity (the pot), banked, paused, day_key,
  day_realised_pnl. `banked` is auto-migrated into old DBs on startup.
- `zones_snapshot` (optional) — periodic dump of active zones for `/zones` and
  debugging.

## Project layout

```
livesignal/
  livesignal/
    __init__.py
    config.py         # load yaml + .env, validate
    broker.py         # ccxt wrapper: fetch_ohlcv, (live) create_market_order
    paper.py          # paper-fill + position tracking mirroring engine.py math
    trader.py         # the signal loop; imports ZoneTracker + confirm from srbounce
    chart.py          # /zones candlestick PNG (matplotlib)
    notify.py         # Telegram send (HTML) + sendPhoto + command handling
    store.py          # SQLite persistence
    risk.py           # daily loss limit, pause state
  config.yaml         # the validated config above
  .env.example        # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET
  pyproject.toml
  Dockerfile
  docker-compose.yml  # single service, restart: unless-stopped, mounts ./data for sqlite
  README.md
```

## Dependencies

`ccxt`, `pandas`, `numpy`, `pyyaml`, `requests` (raw HTTP to the Bot API),
`matplotlib` (zones chart), `srbounce` (from the monorepo root). Python 3.11+.

## Deployment

Docker on the Proxmox stack. `docker-compose up -d`, `restart: unless-stopped`.
Mount a host volume for the SQLite file so state survives container restarts.
Outbound network needed to `api.binance.com` and `api.telegram.org`.

## Build order (steps 1–6 DONE as of 2026-07-24; step 7 pending paper results)

1. `store.py` + `config.py` + `.env` loading — foundation, testable alone.
2. `broker.py` fetch path + `paper.py` — get candles, simulate fills.
3. `trader.py` wiring `srbounce.ZoneTracker`/`confirm` into the paper loop.
   Verify: replay recent history through the live loop and confirm it produces
   the SAME trades the backtester does on the same candles. This is the
   acceptance test for "live logic == backtest logic".
4. `notify.py` — Telegram messages + `/status` `/zones` `/pause` `/resume`.
5. `risk.py` — daily loss limit + pause integration.
6. Dockerize, deploy, run paper for 2–3 months.
7. Only after paper matches backtest: implement live order path in `broker.py`
   and flip `paper: false`.

## Acceptance criteria

- Live loop replayed over historical candles reproduces backtester trades exactly
  (same entries/exits/pnl within rounding). If it doesn't, the divergence must be
  found and fixed before anything else.
- No trade ever opens on an incomplete candle.
- Restart mid-position loses no state and opens no duplicate.
- Daily loss limit and `/pause` both provably block new entries.
- Paper phase runs unattended and its trade log is directly comparable to backtest
  metrics.

## Notes / disclaimers

- This trades real money in Phase 2. Past backtested performance does not
  guarantee future results; the ETH edge is measured, not promised.
- Risk per trade is 11% (half-Kelly) by the user's explicit, informed choice —
  they understand the pot will draw down hard and accepted it; the banked
  balance is the safety valve. Do not silently "fix" this back to 0.5%.
  Any further sizing change should again be argued from the R distribution.
- Binance API keys for Phase 2 should be trade-only (no withdrawal permission),
  IP-restricted to the VM.
