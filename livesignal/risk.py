"""Daily loss limit + pause gate. All state lives in the SQLite `state` row so
it survives restarts.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from . import store


def utc_day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


class RiskManager:
    def __init__(self, conn: sqlite3.Connection, daily_loss_limit_pct: float):
        self.conn = conn
        self.limit_pct = daily_loss_limit_pct

    def _state(self) -> dict:
        return store.get_state(self.conn)

    def roll_day(self, now: datetime | None = None) -> None:
        """Reset the daily realised-PnL counter when the UTC day changes."""
        key = utc_day_key(now)
        if self._state()["day_key"] != key:
            store.update_state(self.conn, day_key=key, day_realised_pnl=0.0)

    def record_realised_pnl(self, pnl: float, now: datetime | None = None) -> None:
        self.roll_day(now)
        st = self._state()
        store.update_state(self.conn, day_realised_pnl=st["day_realised_pnl"] + pnl)

    def daily_limit_tripped(self, now: datetime | None = None) -> bool:
        self.roll_day(now)
        st = self._state()
        return st["day_realised_pnl"] <= -(self.limit_pct / 100) * st["equity"]

    def paused(self) -> bool:
        return bool(self._state()["paused"])

    def set_paused(self, paused: bool) -> None:
        store.update_state(self.conn, paused=int(paused))

    def can_open_new_trade(self, now: datetime | None = None) -> tuple[bool, str]:
        """(allowed, reason-if-blocked). Managing existing trades is never blocked."""
        if self.paused():
            return False, "paused"
        if self.daily_limit_tripped(now):
            return False, "daily_loss_limit"
        return True, ""
