from __future__ import annotations

from ..types import Features, Signal
from .base import Agent

COOLDOWN_S = 1800.0


class Radar:
    """Three agents on rotation; each scan emits up to 3 candidate signals."""

    def __init__(self, agents: list[Agent]) -> None:
        self.agents = agents
        self.turn = 0
        self.last_signal: dict[str, float] = {}
        self.signals_emitted = 0

    def scan(self, feats: dict[str, Features], open_syms: set[str], now: float,
             min_quote_volume: float) -> list[Signal]:
        agent = self.agents[self.turn % len(self.agents)]
        self.turn += 1
        cands: list[Features] = []
        for sym, f in feats.items():
            if sym in open_syms or not f.fresh or f.last <= 0:
                continue
            if f.mom_15m <= 0.0008:                         # raw prefilter
                continue
            if f.vol_surprise < 1.1:
                continue
            if f.quote_volume_24h < min_quote_volume * 0.6:
                continue
            if now - self.last_signal.get(sym, 0.0) < COOLDOWN_S:
                continue
            cands.append(f)
        cands.sort(key=lambda f: -(f.mom_15m * min(f.vol_surprise, 3.0)))
        out: list[Signal] = []
        for f in cands[:3]:
            self.last_signal[f.symbol] = now
            out.append(Signal(symbol=f.symbol, agent=agent.name, ts=now, features=f))
        self.signals_emitted += len(out)
        return out
