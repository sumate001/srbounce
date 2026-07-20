"""Telegram: outbound notifications (plain text, no buttons) + long-poll command
handling for /status /zones /pause /resume.

Raw HTTP to the Bot API via requests — no framework needed for this scope.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("livesignal.notify")

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self._offset = 0

    def _call(self, method: str, **params) -> dict | None:
        try:
            r = requests.post(API.format(token=self.token, method=method),
                              json=params, timeout=30)
            data = r.json()
            if not data.get("ok"):
                log.error("telegram %s failed: %s", method, data)
                return None
            return data["result"]
        except Exception:
            log.exception("telegram %s error", method)
            return None

    def send(self, text: str) -> None:
        for attempt in range(3):
            if self._call("sendMessage", chat_id=self.chat_id, text=text) is not None:
                return
            time.sleep(2 ** attempt)
        log.error("telegram send gave up: %r", text[:200])

    def poll_commands(self) -> list[str]:
        """Fetch pending updates, return commands (e.g. '/pause') from our chat."""
        result = self._call("getUpdates", offset=self._offset, timeout=0)
        if not result:
            return []
        cmds = []
        for upd in result:
            self._offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                continue
            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                cmds.append(text.split("@")[0].split()[0].lower())
        return cmds


# ---- message formatters ----------------------------------------------------

def fmt_trade_opened(market: str, direction: str, entry: float, sl: float, tp: float,
                      risk_pct: float, size: float, zone_center: float, pattern: str,
                      paper: bool) -> str:
    tag = "PAPER" if paper else "LIVE"
    return (f"[{tag}] Trade opened — {market} {direction.upper()}\n"
            f"entry {entry:.2f}  SL {sl:.2f}  TP {tp:.2f}\n"
            f"size {size:.6f}  risk {risk_pct}%\n"
            f"zone {zone_center:.2f}  pattern {pattern}")


def fmt_trade_closed(market: str, direction: str, exit_reason: str, exit_price: float,
                      pnl: float, r_multiple: float, equity: float, paper: bool) -> str:
    tag = "PAPER" if paper else "LIVE"
    return (f"[{tag}] Trade closed — {market} {direction.upper()} ({exit_reason})\n"
            f"exit {exit_price:.2f}  P/L {pnl:+.2f} USDT  ({r_multiple:+.2f}R)\n"
            f"equity {equity:.2f}")


def fmt_btc_signal(direction: str, entry_ref: float, sl: float, tp: float,
                    zone_center: float, pattern: str) -> str:
    return ("[SIGNAL-ONLY] BTCUSDT — observational, no trade opened\n"
            f"would enter {direction.upper()} ~{entry_ref:.2f}\n"
            f"SL {sl:.2f}  TP {tp:.2f}\n"
            f"zone {zone_center:.2f}  pattern {pattern}")


def fmt_status(equity: float, open_trade: dict | None, day_pnl: float, paused: bool,
                paper: bool) -> str:
    lines = [f"mode: {'paper' if paper else 'LIVE'}",
             f"equity: {equity:.2f}",
             f"today P/L: {day_pnl:+.2f}",
             f"paused: {'yes' if paused else 'no'}"]
    if open_trade:
        lines.append(f"open: {open_trade['market']} {open_trade['direction']} "
                     f"@ {open_trade['entry']:.2f} SL {open_trade['sl']:.2f} "
                     f"TP {open_trade['tp']:.2f}")
    else:
        lines.append("open: none")
    return "\n".join(lines)


def fmt_zones(market: str, zones: list[dict]) -> str:
    if not zones:
        return f"{market}: no active zones"
    lines = [f"{market} active zones:"]
    for z in sorted(zones, key=lambda z: z["center"], reverse=True):
        lines.append(f"  {z['kind'][:3]}  {z['lo']:.2f}–{z['hi']:.2f}  "
                     f"(center {z['center']:.2f}, {z['touches']} touches)")
    return "\n".join(lines)


def fmt_weekly_summary(trades: list[dict], equity: float, open_trade: dict | None) -> str:
    n = len(trades)
    wins = sum(1 for t in trades if (t["pnl"] or 0) > 0)
    net = sum(t["pnl"] or 0 for t in trades)
    lines = ["Weekly summary",
             f"trades closed: {n}",
             f"win rate: {wins / n * 100:.0f}%" if n else "win rate: –",
             f"net P/L: {net:+.2f}",
             f"equity: {equity:.2f}"]
    if open_trade:
        lines.append(f"open: {open_trade['market']} {open_trade['direction']} "
                     f"@ {open_trade['entry']:.2f}")
    else:
        lines.append("open: none")
    return "\n".join(lines)
