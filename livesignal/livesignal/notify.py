"""Telegram: outbound notifications (HTML-formatted cards, no buttons) +
long-poll command handling for /status /zones /pause /resume.

Raw HTTP to the Bot API via requests — no framework needed for this scope.
"""
from __future__ import annotations

import html
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
            if self._call("sendMessage", chat_id=self.chat_id, text=text,
                          parse_mode="HTML") is not None:
                return
            # HTML parse errors would retry pointlessly — fall back to plain
            if self._call("sendMessage", chat_id=self.chat_id, text=text) is not None:
                return
            time.sleep(2 ** attempt)
        log.error("telegram send gave up: %r", text[:200])

    def send_photo(self, png: bytes, caption: str = "") -> bool:
        try:
            r = requests.post(API.format(token=self.token, method="sendPhoto"),
                              data={"chat_id": self.chat_id, "caption": caption,
                                    "parse_mode": "HTML"},
                              files={"photo": ("zones.png", png, "image/png")},
                              timeout=60)
            if r.json().get("ok"):
                return True
            log.error("telegram sendPhoto failed: %s", r.text[:300])
        except Exception:
            log.exception("telegram sendPhoto error")
        return False

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
# Telegram has no real "cards"; the closest look is HTML bold headers, emoji
# and <pre> blocks whose monospace columns line up.

RULE = "──────────────"


def esc(s) -> str:
    return html.escape(str(s))


def fmt_trade_opened(market: str, direction: str, entry: float, sl: float, tp: float,
                      risk_pct: float, size: float, zone_center: float, pattern: str,
                      paper: bool) -> str:
    tag = "🧪 PAPER" if paper else "🔴 LIVE"
    arrow = "📈 LONG" if direction == "long" else "📉 SHORT"
    return (f"<b>{tag} · Trade opened</b>\n"
            f"<b>{esc(market)}</b>  {arrow}\n"
            f"{RULE}\n"
            f"<pre>entry  {entry:>10.2f}\n"
            f"SL     {sl:>10.2f}\n"
            f"TP     {tp:>10.2f}\n"
            f"size   {size:>10.6f}\n"
            f"risk   {risk_pct:>9}%</pre>\n"
            f"zone <code>{zone_center:.2f}</code> · pattern <b>{esc(pattern)}</b>")


def fmt_trade_closed(market: str, direction: str, exit_reason: str, exit_price: float,
                      pnl: float, r_multiple: float, equity: float, paper: bool,
                      banked: float = 0.0) -> str:
    tag = "🧪 PAPER" if paper else "🔴 LIVE"
    face = "✅" if pnl >= 0 else "❌"
    reason = {"sl": "stop loss", "tp": "take profit", "time": "time exit"}.get(exit_reason, exit_reason)
    return (f"<b>{tag} · Trade closed {face}</b>\n"
            f"<b>{esc(market)}</b>  {direction.upper()} · {esc(reason)}\n"
            f"{RULE}\n"
            f"<pre>exit    {exit_price:>10.2f}\n"
            f"P/L     {pnl:>+10.2f} USDT\n"
            f"R       {r_multiple:>+10.2f}\n"
            f"pot     {equity:>10.2f}\n"
            f"banked  {banked:>10.2f}</pre>")


def fmt_btc_signal(direction: str, entry_ref: float, sl: float, tp: float,
                    zone_center: float, pattern: str) -> str:
    return ("<b>👀 SIGNAL-ONLY · BTCUSDT</b>\n"
            "<i>observational — no trade opened</i>\n"
            f"{RULE}\n"
            f"<pre>side   {direction.upper():>10}\n"
            f"entry ~{entry_ref:>10.2f}\n"
            f"SL     {sl:>10.2f}\n"
            f"TP     {tp:>10.2f}</pre>\n"
            f"zone <code>{zone_center:.2f}</code> · pattern <b>{esc(pattern)}</b>")


def fmt_status(equity: float, open_trade: dict | None, day_pnl: float, paused: bool,
                paper: bool, banked: float = 0.0) -> str:
    mode = "🧪 paper" if paper else "🔴 LIVE"
    pause = "⏸ paused" if paused else "▶️ running"
    lines = [f"<b>📊 Status</b>  ·  {mode}  ·  {pause}",
             RULE,
             f"<pre>pot        {equity:>10.2f}\n"
             f"banked     {banked:>10.2f}\n"
             f"today P/L  {day_pnl:>+10.2f}</pre>"]
    if open_trade:
        lines.append(f"open: <b>{esc(open_trade['market'])}</b> {open_trade['direction']} "
                     f"@ <code>{open_trade['entry']:.2f}</code> "
                     f"SL <code>{open_trade['sl']:.2f}</code> "
                     f"TP <code>{open_trade['tp']:.2f}</code>")
    else:
        lines.append("open: <i>none</i>")
    return "\n".join(lines)


def fmt_zones(market: str, zones: list[dict]) -> str:
    if not zones:
        return f"<b>🗺 {esc(market)}</b>: no active zones"
    lines = [f"<b>🗺 {esc(market)} · active zones</b>", RULE, "<pre>"]
    for z in sorted(zones, key=lambda z: z["center"], reverse=True):
        icon = "🟥" if z["kind"] == "resistance" else "🟩"
        lines.append(f"{icon} {z['kind'][:3]}  {z['lo']:>9.2f}–{z['hi']:<9.2f} "
                     f"x{z['touches']}")
    lines.append("</pre>")
    return "\n".join(lines)


def fmt_weekly_summary(trades: list[dict], equity: float, open_trade: dict | None) -> str:
    n = len(trades)
    wins = sum(1 for t in trades if (t["pnl"] or 0) > 0)
    net = sum(t["pnl"] or 0 for t in trades)
    wr = f"{wins / n * 100:.0f}%" if n else "–"
    lines = ["<b>🗓 Weekly summary</b>",
             RULE,
             f"<pre>closed    {n:>10}\n"
             f"win rate  {wr:>10}\n"
             f"net P/L   {net:>+10.2f}\n"
             f"equity    {equity:>10.2f}</pre>"]
    if open_trade:
        lines.append(f"open: <b>{esc(open_trade['market'])}</b> {open_trade['direction']} "
                     f"@ <code>{open_trade['entry']:.2f}</code>")
    else:
        lines.append("open: <i>none</i>")
    return "\n".join(lines)
