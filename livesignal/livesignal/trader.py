"""The signal loop.

Strategy logic is IMPORTED from srbounce (ZoneTracker, confirm via
engine.evaluate_setup / engine.evaluate_exit) — never reimplemented here.
Per-bar order of operations mirrors srbounce.engine.run_backtest:
manage open trade first, then update zones, then look for a new setup.

Live-vs-backtest fill difference (intentional, per spec): the backtester fills
a signal at the NEXT bar's open; live fills at the current market price right
after the signal bar closes — the same moment in time.
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd

from srbounce.engine import Trade, evaluate_exit, evaluate_setup
from srbounce.signals import trend_direction
from srbounce.zones import ZoneTracker

from . import notify, store
from .broker import Broker
from .config import AppConfig, MarketConfig
from .paper import PaperBroker
from .risk import RiskManager

log = logging.getLogger("livesignal.trader")

TF_HOURS = {"1h": 1, "4h": 4, "1d": 24}
COMMAND_POLL_SEC = 30


def timeframe_delta(timeframe: str) -> timedelta:
    return timedelta(hours=TF_HOURS[timeframe])


def next_candle_close(now: datetime, timeframe: str) -> datetime:
    """Next UTC candle boundary strictly after `now` (Binance UTC-aligned)."""
    step = timeframe_delta(timeframe)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    boundary = day
    while boundary <= now:
        boundary += step
    return boundary


def closed_candles(df: pd.DataFrame, timeframe: str, now: datetime) -> pd.DataFrame:
    """Drop the still-forming candle: keep bars whose close time is <= now."""
    cutoff = pd.Timestamp(now) - timeframe_delta(timeframe)
    return df[df.index <= cutoff]


def seed_zone_tracker(df: pd.DataFrame, s: dict) -> ZoneTracker:
    """Walk the whole history through ZoneTracker exactly as the backtester does."""
    zt = ZoneTracker(df, s["swing_lookback"], s["zone_atr_mult"],
                     s["zone_max_age_bars"], s["min_touches"])
    for t in range(1, len(df)):
        zt.update(t)
    return zt


def bars_held(df: pd.DataFrame, entry_time: str) -> int:
    """Number of decision bars since entry: the backtester's t - entry_bar."""
    ts = pd.Timestamp(entry_time)
    entry_pos = df.index.searchsorted(ts)
    return (len(df) - 1) - entry_pos


class TraderService:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.conn = store.connect(cfg.db_path)
        store.init_state(self.conn, cfg.risk["initial_equity"],
                         datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.risk = RiskManager(self.conn, cfg.risk["daily_loss_limit_pct"])
        self.paper = PaperBroker(cfg.risk["fee_pct"], cfg.risk["slippage_pct"])
        self.tg = notify.Telegram(cfg.secrets.telegram_bot_token,
                                  cfg.secrets.telegram_chat_id)
        self.brokers = {
            name: Broker(m.exchange, cfg.secrets.binance_api_key,
                         cfg.secrets.binance_secret, paper=cfg.paper)
            for name, m in cfg.markets.items()
        }
        self._zones_cache: dict[str, list[dict]] = {}
        self._last_weekly: str = ""

    # ---- per-market cycle ---------------------------------------------------

    def run_market_cycle(self, m: MarketConfig, now: datetime) -> None:
        broker = self.brokers[m.name]
        df_raw = broker.fetch_ohlcv(m.symbol, m.timeframe,
                                    self.cfg.data["history_bars"])
        df = closed_candles(df_raw, m.timeframe, now)
        if len(df) < 250:
            raise RuntimeError(f"{m.name}: only {len(df)} closed candles fetched")
        t = len(df) - 1  # decision bar = newest CLOSED candle

        s = self.cfg.strategy

        # 1. manage open trade against the decision bar
        open_row = store.get_open_trade(self.conn, m.name)
        if open_row is not None:
            held = bars_held(df, open_row["entry_time"])
            tr = Trade(entry_bar=t - held, entry_time=pd.Timestamp(open_row["entry_time"]),
                       direction=open_row["direction"], entry=open_row["entry"],
                       sl=open_row["sl"], tp=open_row["tp"], size=open_row["size"],
                       zone_center=open_row["zone_center"], pattern=open_row["pattern"])
            result = evaluate_exit(df, t, tr, s)
            if result is not None:
                self._close_trade(m, open_row, result, df.index[t])
                open_row = None

        # 2+3. zones from full history, then setup on the decision bar
        zt = seed_zone_tracker(df, s)
        self._zones_cache[m.name] = [
            {"center": z.center, "lo": z.lo, "hi": z.hi, "kind": z.kind,
             "touches": z.touches} for z in zt.active()
        ]
        store.save_zones_snapshot(self.conn, m.name, df.index[t].isoformat(),
                                  self._zones_cache[m.name])

        trend = trend_direction(df, s.get("trend_filter"))
        setup = evaluate_setup(df, t, zt, trend, s)
        if setup is None or open_row is not None:
            return

        if not m.tradeable:
            self.tg.send(notify.fmt_btc_signal(
                setup["direction"], df["close"].iloc[t], setup["sl"], setup["tp"],
                setup["zone_center"], setup["pattern"]))
            return

        allowed, reason = self.risk.can_open_new_trade(now)
        if not allowed:
            self.tg.send(f"Signal on {m.name} skipped: {reason}")
            return

        self._open_trade(m, broker, setup, df.index[t])

    # ---- fills --------------------------------------------------------------

    def _open_trade(self, m: MarketConfig, broker: Broker, setup: dict,
                     bar_close_time: pd.Timestamp) -> None:
        # practical live fill = current price right after the signal bar close
        try:
            raw_px = broker.fetch_last_price(m.symbol)
        except Exception:
            log.exception("ticker fetch failed, aborting entry")
            self.tg.send(f"ERROR: could not fetch price for {m.name}; entry skipped")
            return

        equity = store.get_state(self.conn)["equity"]
        fill = self.paper.fill_entry(equity, setup["direction"], raw_px,
                                     setup["sl"], self.cfg.risk["risk_pct"])
        if not self.cfg.paper:
            side = "buy" if setup["direction"] == "long" else "sell"
            order = broker.create_market_order(m.symbol, side, fill.size)
            fill.price = float(order.get("average") or fill.price)

        # TP comes from evaluate_setup (anchored to the signal bar's close),
        # NOT recomputed from the fill — that is what the backtester does, and
        # parity with the backtester overrides everything else.
        tp = setup["tp"]

        entry_time = (bar_close_time + timeframe_delta(m.timeframe)).isoformat()
        store.insert_trade(self.conn, m.name, setup["direction"], entry_time,
                           fill.price, setup["sl"], tp, fill.size,
                           setup["zone_center"], setup["pattern"], self.cfg.paper)
        store.update_state(self.conn, equity=fill.equity_after)
        self.tg.send(notify.fmt_trade_opened(
            m.name, setup["direction"], fill.price, setup["sl"], tp,
            self.cfg.risk["risk_pct"], fill.size, setup["zone_center"],
            setup["pattern"], self.cfg.paper))

    def _close_trade(self, m: MarketConfig, row: dict,
                      result: tuple[float, str], bar_time: pd.Timestamp) -> None:
        raw_exit_px, reason = result
        equity = store.get_state(self.conn)["equity"]
        ex = self.paper.fill_exit(equity, row["direction"], row["entry"],
                                  row["sl"], row["size"], raw_exit_px)
        if not self.cfg.paper:
            side = "sell" if row["direction"] == "long" else "buy"
            order = self.brokers[m.name].create_market_order(m.symbol, side, row["size"])
            actual = float(order.get("average") or 0) or None
            if actual:
                ex = self.paper.fill_exit(equity, row["direction"], row["entry"],
                                          row["sl"], row["size"], actual)

        store.close_trade(self.conn, row["id"], bar_time.isoformat(), ex.price,
                          reason, ex.pnl, ex.r_multiple)
        store.update_state(self.conn, equity=ex.equity_after)
        self.risk.record_realised_pnl(ex.pnl)
        if self.risk.daily_limit_tripped():
            self.tg.send("Daily loss limit tripped — no new entries until next UTC day.")
        self.tg.send(notify.fmt_trade_closed(
            m.name, row["direction"], reason, ex.price, ex.pnl, ex.r_multiple,
            ex.equity_after, bool(row["paper"])))

    # ---- telegram commands --------------------------------------------------

    def handle_commands(self) -> None:
        for cmd in self.tg.poll_commands():
            if cmd == "/pause":
                self.risk.set_paused(True)
                self.tg.send("Paused — no new entries. Open trades still managed. /resume to re-enable.")
            elif cmd == "/resume":
                self.risk.set_paused(False)
                self.tg.send("Resumed — new entries enabled.")
            elif cmd == "/status":
                st = store.get_state(self.conn)
                open_trade = None
                for name in self.cfg.markets:
                    open_trade = open_trade or store.get_open_trade(self.conn, name)
                self.tg.send(notify.fmt_status(st["equity"], open_trade,
                                               st["day_realised_pnl"],
                                               bool(st["paused"]), self.cfg.paper))
            elif cmd == "/zones":
                zones = self._zones_cache.get("ETHUSDT") \
                    or store.latest_zones_snapshot(self.conn, "ETHUSDT")
                if not self._send_zones_chart("ETHUSDT", zones):
                    self.tg.send(notify.fmt_zones("ETHUSDT", zones))
            elif cmd.startswith("/"):
                self.tg.send(f"Unknown command: {notify.esc(cmd)}\n"
                             "Available: /status /zones /pause /resume")

    def _send_zones_chart(self, market: str, zones: list[dict]) -> bool:
        if not zones:
            return False
        try:
            from . import chart
            m = self.cfg.markets[market]
            df = self.brokers[market].fetch_ohlcv(m.symbol, m.timeframe, 100)
            pad = (df["high"].max() - df["low"].min()) * 0.06
            visible = [z for z in zones
                       if z["hi"] >= df["low"].min() - pad
                       and z["lo"] <= df["high"].max() + pad]
            png = chart.render_zones_png(df, visible, market, m.timeframe)
            caption = notify.fmt_zones(market, visible)
            return self.tg.send_photo(png, caption)
        except Exception:
            log.exception("zones chart failed, falling back to text")
            return False

    def maybe_weekly_summary(self, now: datetime) -> None:
        # Monday after the first candle close of the UTC day
        week_key = f"{now.isocalendar().year}-W{now.isocalendar().week}"
        if now.weekday() != 0 or week_key == self._last_weekly:
            return
        self._last_weekly = week_key
        since = (now - timedelta(days=7)).isoformat()
        trades = store.recent_closed_trades(self.conn, since=since)
        st = store.get_state(self.conn)
        open_trade = None
        for name in self.cfg.markets:
            open_trade = open_trade or store.get_open_trade(self.conn, name)
        self.tg.send(notify.fmt_weekly_summary(trades, st["equity"], open_trade))

    # ---- main loop ----------------------------------------------------------

    def run_forever(self) -> None:
        mode = "paper" if self.cfg.paper else "LIVE"
        self.tg.send(f"livesignal started ({mode}). Markets: "
                     + ", ".join(f"{n} [{m.mode}]" for n, m in self.cfg.markets.items()))
        while True:
            now = datetime.now(timezone.utc)
            wake_at = next_candle_close(now, "4h") \
                + timedelta(seconds=self.cfg.data["poll_after_close_sec"])
            log.info("sleeping until %s", wake_at)
            while datetime.now(timezone.utc) < wake_at:
                try:
                    self.handle_commands()
                except Exception:
                    log.exception("command handling error")
                remaining = (wake_at - datetime.now(timezone.utc)).total_seconds()
                time.sleep(max(0, min(COMMAND_POLL_SEC, remaining)))

            now = datetime.now(timezone.utc)
            for m in self.cfg.markets.values():
                try:
                    self.run_market_cycle(m, now)
                except Exception as e:
                    # fail safe: never open trades on error; keep the loop alive
                    log.exception("cycle error on %s", m.name)
                    self.tg.send(f"ERROR in {m.name} cycle: {e}\n"
                                 f"{traceback.format_exc(limit=3)}")
            try:
                self.maybe_weekly_summary(now)
            except Exception:
                log.exception("weekly summary error")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from .config import load_config
    cfg = load_config()
    TraderService(cfg).run_forever()


if __name__ == "__main__":
    main()
