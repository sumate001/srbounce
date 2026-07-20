"""Walk-forward S/R zone detection — no lookahead.

A swing high at bar i is only *known* at bar i + lookback (needs `lookback`
bars on the right to confirm). Zones are built incrementally: at bar t the
zone set reflects only swings confirmed at or before t.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Zone:
    center: float
    half_width: float
    kind: str            # "support" | "resistance"
    created_bar: int
    touches: int = 1
    touch_bars: list = field(default_factory=list)

    @property
    def lo(self) -> float:
        return self.center - self.half_width

    @property
    def hi(self) -> float:
        return self.center + self.half_width

    def contains(self, price: float) -> bool:
        return self.lo <= price <= self.hi


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def find_swings(df: pd.DataFrame, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Return boolean arrays (swing_high, swing_low) at the swing bar index.

    A swing is *confirmed* `lookback` bars later — callers must respect that.
    """
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        win_h = h[i - lookback : i + lookback + 1]
        win_l = l[i - lookback : i + lookback + 1]
        if h[i] == win_h.max() and (win_h == h[i]).sum() == 1:
            sh[i] = True
        if l[i] == win_l.min() and (win_l == l[i]).sum() == 1:
            sl[i] = True
    return sh, sl


class ZoneTracker:
    """Incrementally maintains zones as bars arrive (walk-forward)."""

    def __init__(self, df: pd.DataFrame, lookback: int, atr_mult: float,
                 max_age: int, min_touches: int):
        self.df = df
        self.lookback = lookback
        self.atr_mult = atr_mult
        self.max_age = max_age
        self.min_touches = min_touches
        self.atr = atr(df).values
        self.sh, self.sl = find_swings(df, lookback)
        self.zones: list[Zone] = []

    def _merge_or_add(self, price: float, kind: str, bar: int) -> None:
        hw = self.atr_mult * self.atr[bar]
        if not np.isfinite(hw) or hw <= 0:
            return
        for z in self.zones:
            if z.kind == kind and abs(z.center - price) <= max(z.half_width, hw):
                z.center = (z.center * z.touches + price) / (z.touches + 1)
                z.touches += 1
                z.touch_bars.append(bar)
                z.half_width = max(z.half_width, hw)
                return
        self.zones.append(Zone(price, hw, kind, bar, touches=1, touch_bars=[bar]))

    def update(self, t: int) -> None:
        """Advance to bar t: absorb swings confirmed exactly at t, prune old zones."""
        s = t - self.lookback  # swing bar confirmed now
        if s >= self.lookback:
            if self.sh[s]:
                self._merge_or_add(self.df["high"].iloc[s], "resistance", s)
            if self.sl[s]:
                self._merge_or_add(self.df["low"].iloc[s], "support", s)
        self.zones = [z for z in self.zones
                      if t - (z.touch_bars[-1] if z.touch_bars else z.created_bar) <= self.max_age]

    def active(self) -> list[Zone]:
        return [z for z in self.zones if z.touches >= self.min_touches]
