"""Reversal-confirmation candle patterns and trend filter."""
from __future__ import annotations

import pandas as pd


def is_bullish_pin(o: float, h: float, l: float, c: float) -> bool:
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    return lower_wick >= 0.6 * rng and body <= 0.35 * rng and c > o


def is_bearish_pin(o: float, h: float, l: float, c: float) -> bool:
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    return upper_wick >= 0.6 * rng and body <= 0.35 * rng and c < o


def is_bullish_engulfing(po: float, pc: float, o: float, c: float) -> bool:
    return pc < po and c > o and c >= po and o <= pc


def is_bearish_engulfing(po: float, pc: float, o: float, c: float) -> bool:
    return pc > po and c < o and c <= po and o >= pc


def confirm(df: pd.DataFrame, i: int, direction: str, patterns: list[str]) -> str | None:
    """Check bar i for a reversal candle in `direction` ('long'|'short')."""
    o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
    po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    if direction == "long":
        if "pin" in patterns and is_bullish_pin(o, h, l, c):
            return "bullish_pin"
        if "engulfing" in patterns and is_bullish_engulfing(po, pc, o, c):
            return "bullish_engulfing"
    else:
        if "pin" in patterns and is_bearish_pin(o, h, l, c):
            return "bearish_pin"
        if "engulfing" in patterns and is_bearish_engulfing(po, pc, o, c):
            return "bearish_engulfing"
    return None


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def trend_direction(df: pd.DataFrame, kind: str | None) -> pd.Series:
    """+1 above EMA200, -1 below, 0 = no filter. Uses close of the SAME bar,
    which is known at bar close when signals are evaluated."""
    if not kind:
        return pd.Series(0, index=df.index)
    if kind == "ema200":
        e = ema(df["close"], 200)
        return (df["close"] > e).astype(int) * 2 - 1
    raise ValueError(f"unknown trend filter: {kind}")
