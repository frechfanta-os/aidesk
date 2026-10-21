from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Features:
    symbol: str
    last: float
    bid: float | None
    ask: float | None
    quote_volume_24h: float
    mom_15m: float              # fraction, e.g. 0.002 = +0.2 %
    mom_1h: float
    vol_surprise: float         # quoteVolume15min_ish vs 24h pace (x)
    range_pct: float            # high-low / pct of 24h
    fresh: bool = True
    ts: float = 0.0             # epoch de l'observation (0.0 = fraîcheur inconnue)

    def age(self, now: float) -> float | None:
        """Âge de l'observation en secondes ; None si le ts est inconnu/inviable.

        Cas distingués : fraîche (âge <= seuil, décidé par l'appelant), périmée
        (âge > seuil), invalide (ts négatif), fraîcheur inconnue (ts <= 0 ou décalage
        horloge suspect). Une donnée absente stylée différemment : il n'y a pas
        d'objet Features du tout (jamais un objet à valeurs zéro)."""
        if self.ts <= 0.0 or self.ts > now + 300.0:   # inconnu, invalide ou skew horloge
            return None
        return max(0.0, now - self.ts)

    def usable(self, now: float, max_age: float) -> bool:
        """Vrai si l'observation peut déclencher une décision d'entrée."""
        a = self.age(now)
        return self.fresh and a is not None and a <= max_age


@dataclass
class Signal:
    symbol: str
    agent: str
    ts: float
    features: Features


@dataclass
class Decision:
    ts: float
    symbol: str
    agent: str
    scores: dict[str, float]
    agg: float
    verdict: bool
    thesis: str
    objection: str | None = None


@dataclass
class Position:
    symbol: str
    entry: float
    qty: float
    usdt: float
    ts_open: float
    agent: str
    approver: str | None
    features: Features
    score: float


@dataclass
class Trade:
    symbol: str
    entry: float
    exit: float
    qty: float
    pnl: float
    reason: str
    ts_open: float
    ts_close: float
    agent: str
    approver: str | None
    score: float
    features: Features = field(default_factory=lambda: Features("", 0, None, None, 0, 0, 0, 0, 0))
