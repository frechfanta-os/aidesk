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
