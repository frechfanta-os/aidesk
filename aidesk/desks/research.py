from __future__ import annotations

import json

from .. import llm
from ..types import Decision, Signal
from .base import Agent, clamp01

_MAX_OBJ_CHARS = 160


def _sanitize_objection(obj) -> str | None:
    """Sortie SKEPTIC = entrée NON FIABLE : texte nettoyé et borné, sinon None.

    Une objection n'influence jamais verdict/agg ; elle est seulement journalisée.
    Non-str (exception, dict…), vide ou blanches → None. Bornées à _MAX_OBJ_CHARS."""
    if not isinstance(obj, str):
        return None
    t = " ".join(obj.split())                  # espaces/newlines/control chars collapsés
    return t[:_MAX_OBJ_CHARS] or None


def _extract_objection(raw) -> str | None:
    """B3+ : tente le schéma JSON {"objection": <str>} ; sinon texte libre borné.

    La sortie LLM reste une entrée NON FIABLE dans les deux cas : re-nettoyée,
    bornée à _MAX_OBJ_CHARS, jamais décisionnelle. JSON dict sans champ
    `objection` string → None (structure présente mais vide → pas d'objection)."""
    text = _sanitize_objection(raw)
    if text is None:
        return None
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = json.loads(t)
        except Exception:
            return text                       # JSON malformé → le texte borné reste
        if isinstance(obj, dict):
            val = obj.get("objection")
            if isinstance(val, str) and _sanitize_objection(val):
                return _sanitize_objection(val)   # re-borne le champ extracté
            return None
    return text


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
        obj = None
        if verdict:                                # B3 : le SKEPTIC n'est appelé que
            try:                                   # sur un candidat accepté (utile);
                obj = _extract_objection(llm.critique(  # toute sortie est non fiable.
                    f"{f.symbol} last={f.last} mom15={f.mom_15m:.4f} "
                    f"mom1h={f.mom_1h:.4f} vol_surprise={f.vol_surprise:.2f} "
                    f"qv={f.quote_volume_24h:.0f}",
                    thesis,
                ))
            except Exception:                      # aucune panne LLM ne perd une décision
                obj = None
        if obj:
            self.skeptics += 1
        d = Decision(ts=now, symbol=sig.symbol, agent=agent.name, scores=scores,
                     agg=round(agg, 3), verdict=verdict, thesis=thesis,
                     objection=obj)
        self.decisions_made += 1
        self.store.add_decision(d)
        return d
