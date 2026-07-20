"""Paper-fill math — copied verbatim from srbounce.engine.run_backtest's fill/exit
arithmetic (fee_pct/slippage_pct as percent, size from risk_pct, r_multiple from
gross pnl before fees) so a paper trade's numbers are directly comparable to the
backtester's trade log.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fill:
    price: float
    size: float
    equity_after: float


@dataclass
class ExitFill:
    price: float
    pnl: float          # gross, before fees (matches engine.Trade.pnl)
    r_multiple: float
    equity_after: float


class PaperBroker:
    def __init__(self, fee_pct: float, slippage_pct: float):
        self.fee = fee_pct / 100
        self.slip = slippage_pct / 100

    def fill_entry(self, equity: float, direction: str, raw_price: float,
                    sl: float, risk_pct: float) -> Fill:
        px = raw_price * (1 + self.slip) if direction == "long" else raw_price * (1 - self.slip)
        risk_dist = abs(px - sl)
        if risk_dist <= 0:
            raise ValueError("entry price equals stop loss — cannot size position")
        risk_amt = equity * risk_pct / 100
        size = risk_amt / risk_dist
        equity_after = equity - px * size * self.fee
        return Fill(price=px, size=size, equity_after=equity_after)

    def fill_exit(self, equity: float, direction: str, entry: float, sl: float,
                   size: float, raw_exit_price: float) -> ExitFill:
        exit_px = raw_exit_price * (1 - self.slip) if direction == "long" else raw_exit_price * (1 + self.slip)
        gross = (exit_px - entry) * size if direction == "long" else (entry - exit_px) * size
        equity_after = equity + gross - exit_px * size * self.fee
        r_multiple = gross / (abs(entry - sl) * size)
        return ExitFill(price=exit_px, pnl=gross, r_multiple=r_multiple, equity_after=equity_after)
