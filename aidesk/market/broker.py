from __future__ import annotations

import time

from ..config import Settings
from ..types import Position, Trade
from .ledger import Ledger


class PaperBroker:
    """Fills paper positions against the live snapshot with fee + slippage."""

    def __init__(self, ledger: Ledger, settings: Settings) -> None:
        self.ledger = ledger
        self.s = settings
        self.open: dict[str, Position] = {}
        self.fees_paid = 0.0

    def buy(self, f, usdt: float, agent: str, approver: str | None) -> Position:
        price = (f.ask or f.last) * (1 + self.s.slippage_bps / 10_000)
        fee = usdt * self.s.fee_bps / 10_000
        qty = (usdt - fee) / price
        self.ledger.wallet_usdt -= usdt
        self.fees_paid += fee
        pos = Position(symbol=f.symbol, entry=price, qty=qty, usdt=usdt,
                       ts_open=time.time(), agent=agent, approver=approver,
                       features=f, score=0.0)
        self.open[f.symbol] = pos
        return pos

    def settle(self, f, pos: Position, price: float, reason: str) -> Trade:
        price = price * (1 - self.s.slippage_bps / 10_000)
        proceeds = pos.qty * price
        fee = proceeds * self.s.fee_bps / 10_000
        proceeds -= fee
        self.fees_paid += fee
        self.ledger.wallet_usdt += proceeds
        pnl = round(proceeds - pos.usdt, 4)
        trade = Trade(symbol=pos.symbol, entry=pos.entry, exit=price, qty=pos.qty,
                      pnl=pnl, reason=reason, ts_open=pos.ts_open, ts_close=time.time(),
                      agent=pos.agent, approver=pos.approver, score=pos.score,
                      features=f)
        self.ledger.trades.append(trade)
        self.open.pop(pos.symbol, None)
        return trade

    def target_price(self, sym: str, last: float) -> tuple[str, float] | None:
        """TP/SL evaluation against live last price."""
        p = self.open.get(sym)
        if not p:
            return None
        move = (last - p.entry) / p.entry
        if move >= self.s.take_profit:
            return ("TP", last)
        if move <= self.s.stop_loss:
            return ("SL", last)
        return None
