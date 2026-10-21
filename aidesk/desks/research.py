from __future__ import annotations

from .. import llm
from ..types import Decision, Signal
from .base import Agent, clamp01


class Research:
    """MEMORY score-cards a signal against the mutable scoring matrix."""

    def __init__(self, agents: list[Agent], matrix, store) -> None:
        self.agents = agents
        self.turn = 0
        self.m = matrix
        self.store = store
        self.decisions_made = 0
        self.skeptics = 0

    def decide(self, sig: Signal, now: float) -> Decision:
        agent = self.agents[self.turn % len(self.agents)]
        self.turn += 1
        f = sig.features
        m = self.m
        checks = {
            "momentum": f.mom_15m >= m.min_momentum,
            "volume_surprise": f.vol_surprise >= m.min_vol_surprise,
            "overextension": f.mom_1h <= m.max_momentum_1h,
            "liquidity": f.quote_volume_24h >= m.min_quote_volume,
        }
        s_mom = clamp01(f.mom_15m / 0.004)
        s_vol = clamp01((f.vol_surprise - 1.0) / 2.0)
        s_over = 1.0 - clamp01(max(0.0, f.mom_1h) / 0.08)
        s_liq = clamp01(f.quote_volume_24h / 50_000_000.0)
        scores = {"momentum": round(s_mom, 3), "volume": round(s_vol, 3),
                  "overextension": round(s_over, 3), "liquidity": round(s_liq, 3)}
        agg = (m.w_momentum * s_mom + m.w_volume * s_vol
               + m.w_overext * s_over + m.w_liquidity * s_liq)
        verdict = all(checks.values()) and agg >= m.pass_threshold
        thesis = llm.describe(f, checks, round(agg, 3), verdict)
        obj = llm.critique(
            f"{f.symbol} last={f.last} mom15={f.mom_15m:.4f} mom1h={f.mom_1h:.4f} "
            f"vol_surprise={f.vol_surprise:.2f} qv={f.quote_volume_24h:.0f}",
            thesis,
        )
        if obj:
            self.skeptics += 1
        d = Decision(ts=now, symbol=sig.symbol, agent=agent.name, scores=scores,
                     agg=round(agg, 3), verdict=verdict, thesis=thesis,
                     objection=obj if verdict else None)
        self.decisions_made += 1
        self.store.add_decision(d)
        return d
