"""Data adapters: fetch OHLC into a standard DataFrame and cache to parquet.

Standard schema: index = UTC DatetimeIndex, columns = open, high, low, close, volume
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def _cache_path(cache_dir: str, name: str) -> Path:
    p = Path(cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{name}.parquet"


def fetch_ccxt(exchange: str, symbol: str, timeframe: str, start: str) -> pd.DataFrame:
    import ccxt

    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    since = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows: list = []
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        since = batch[-1][0] + 1
        time.sleep(ex.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["ts", *COLS])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    return df[COLS].astype(float)


def fetch_yfinance(symbol: str, timeframe: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    interval = {"1d": "1d", "1h": "1h", "4h": "1h"}.get(timeframe, "1d")
    df = yf.download(symbol, start=start, interval=interval, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[COLS]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if timeframe == "4h" and interval == "1h":
        df = (
            df.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )
    return df.astype(float)


def load_market(mkt: dict, start: str, cache_dir: str, refresh: bool = False) -> pd.DataFrame:
    start = mkt.get("start", start)
    cache = _cache_path(cache_dir, mkt["name"])
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    if mkt["adapter"] == "ccxt":
        df = fetch_ccxt(mkt["exchange"], mkt["symbol"], mkt["timeframe"], start)
    elif mkt["adapter"] == "yfinance":
        df = fetch_yfinance(mkt["symbol"], mkt["timeframe"], start)
    else:
        raise ValueError(f"unknown adapter: {mkt['adapter']}")
    if df.empty:
        raise RuntimeError(f"no data returned for {mkt['name']}")
    df.to_parquet(cache)
    return df
