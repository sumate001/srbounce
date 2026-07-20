"""ccxt wrapper: fetch recent OHLC, and (live-only) submit market orders.

Uses the same standard schema as srbounce.data (UTC DatetimeIndex,
columns open/high/low/close/volume) so candles feed ZoneTracker/confirm
unchanged.
"""
from __future__ import annotations

import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


class Broker:
    def __init__(self, exchange: str, api_key: str = "", secret: str = "", paper: bool = True):
        import ccxt

        params = {"enableRateLimit": True}
        if api_key and secret:
            params["apiKey"] = api_key
            params["secret"] = secret
        self.exchange = getattr(ccxt, exchange)(params)
        self.paper = paper

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """Last `limit` candles, INCLUDING the still-forming one (caller must
        drop it — see trader.decision_bar_index)."""
        batch = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(batch, columns=["ts", *COLS])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.drop_duplicates("ts").set_index("ts").sort_index()
        return df[COLS].astype(float)

    def fetch_last_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    def create_market_order(self, symbol: str, side: str, amount: float) -> dict:
        """Live only. side: 'buy' | 'sell'. Never called when paper=True."""
        if self.paper:
            raise RuntimeError("create_market_order called while paper=True")
        return self.exchange.create_order(symbol, "market", side, amount)
