from __future__ import annotations

from ..types import Decision, Features, Position
from .base import Agent

MIN_TRADE_USDT = 1.0


class ExecutionDesk:
    """Six exec agents on rotation. Sizing = risk cap × agent budget."""

    def __init__(self, agents: list[Agent], broker, risk, store) -> None:
        self.agents = agents
        self.turn = 0
        self.broker = broker
        self.risk = risk
        self.store = store
        self.entries_made = 0

    def try_entry(self, f: Features, d: Decision, now: float) -> Position | None:
        if f.symbol in self.broker.open:
            return None
        ok, why = self.risk.allow(len(self.broker.open), now)
        if not ok:
            self.store.add_event("risk_block", {"symbol": f.symbol, "reason": why})
            return None
        exec_agent = self.agents[self.turn % len(self.agents)]
        self.turn += 1
        size = self.risk.size_for(exec_agent.budget)
        if size < MIN_TRADE_USDT and self.risk.ledger.wallet_usdt >= MIN_TRADE_USDT:
            size = MIN_TRADE_USDT
        size = min(size, round(self.risk.ledger.wallet_usdt, 2))
        if size < MIN_TRADE_USDT:
            self.store.add_event("risk_block", {"symbol": f.symbol, "reason": "taille < $1"})
            return None
        pos = self.broker.buy(f, size, exec_agent.name, d.agent)
        pos.score = d.agg
        self.risk.note_entry(now)
        self.entries_made += 1
        self.store.add_event("entry", {
            "symbol": f.symbol, "usdt": size, "price": pos.entry,
            "agent": exec_agent.name, "approver": d.agent, "score": d.agg,
        })
        return pos
