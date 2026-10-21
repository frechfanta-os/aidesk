from __future__ import annotations

import os
import time
import warnings
from dataclasses import dataclass, field
from typing import Any

import yaml

warnings.filterwarnings("ignore")


CORE_EXCHANGES = ["binance", "bybit", "okx", "kraken", "gate"]


@dataclass
class Matrix:
    """Weights/thresholds RESEARCH uses. AUDIT tightens them within _CLAMP."""

    w_momentum: float = 0.35
    w_volume: float = 0.25
    w_overext: float = 0.20
    w_liquidity: float = 0.20
    min_momentum: float = 0.0015
    max_momentum_1h: float = 0.06
    min_vol_surprise: float = 1.5
    min_quote_volume: float = 5_000_000.0
    pass_threshold: float = 0.62
    revisions: int = 0
    history: list[tuple[int, str]] = field(default_factory=list)

    _CLAMP = {
        "min_momentum": (0.0008, 0.005),
        "max_momentum_1h": (0.02, 0.12),
        "min_vol_surprise": (1.0, 3.0),
        "pass_threshold": (0.55, 0.74),
    }

    def tighten(self, note: str, **deltas: float) -> None:
        moved = False
        for k, d in deltas.items():
            lo, hi = self._CLAMP.get(k, (-1e9, 1e9))
            new = round(min(hi, max(lo, getattr(self, k) + d)), 5)
            if new != getattr(self, k):
                setattr(self, k, new)
                moved = True
        if moved:
            self.revisions += 1
            self.history.append((self.revisions, note))

    def relax(self, note: str, **deltas: float) -> None:
        self.tighten(note, **deltas)


@dataclass
class Settings:
    start_usdt: float = 30.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    take_profit: float = 0.012
    stop_loss: float = -0.008
    max_hold_minutes: float = 90.0
    max_position_fraction: float = 0.25
    max_open_positions: int = 3
    max_entries_per_hour: int = 6
    daily_loss_stop: float = -0.10
    sweep_every_h: int = 24
    freeze_below: float = 0.60
    top_n: int = 40
    refresh_seconds: int = 60
    reviews_every_h: int = 1
    fires_below: float = 0.40
    cooldown_h: int = 6
    dex_enabled: bool = False
    freshness_s: float = 300.0  # B2 : âge max d'une observation pour déclencher une entrée
    desk_agents: dict = None  # populated from desk.yaml at load

    @classmethod
    def load(cls, path: str = "desk.yaml") -> tuple["Settings", Matrix]:
        if not os.path.exists(path):
            return cls(), Matrix()
        with open(path) as f:
            cfg = yaml.safe_load(f)
        s = cfg.get("desks", {})
        ex = s.get("execution", {})
        rs = s.get("research", {})
        m = rs.get("scoring_matrix", {})
        rk = s.get("risk", {})
        tr = s.get("treasury", {})
        hd = cfg.get("head", {})
        pp = cfg.get("paper", {})
        uv = cfg.get("universe", {})
        dx = cfg.get("dex", {})
        fd = cfg.get("feed", {})
        settings = cls(
            take_profit=ex.get("take_profit", cls().take_profit),
            stop_loss=ex.get("stop_loss", cls().stop_loss),
            max_hold_minutes=ex.get("max_hold_minutes", cls().max_hold_minutes),
            max_position_fraction=rk.get("max_position_fraction", 0.25),
            max_open_positions=rk.get("max_open_positions", 3),
            max_entries_per_hour=rk.get("max_entries_per_hour", 6),
            daily_loss_stop=rk.get("daily_loss_stop", -0.10),
            sweep_every_h=tr.get("sweep_every_h", 24),
            freeze_below=tr.get("freeze_below_start_fraction", 0.60),
            reviews_every_h=hd.get("reviews_every_h", 1),
            fires_below=hd.get("fires_below_score", 0.40),
            cooldown_h=hd.get("cooldown_h", 6),
            start_usdt=pp.get("start_usdt", 30.0),
            fee_bps=pp.get("fee_bps", 10.0),
            slippage_bps=pp.get("slippage_bps", 5.0),
            top_n=uv.get("top_by_quote_volume", 40),
            refresh_seconds=uv.get("refresh_seconds", 60),
            dex_enabled=bool(dx.get("enabled", False)),
            freshness_s=float(fd.get("freshness_s", 300.0)),
        )
        desk_agents: dict[str, list[str]] = {}
        for desk, body in (cfg.get("desks") or {}).items():
            if isinstance(body, dict) and body.get("agents"):
                desk_agents[desk] = [str(n) for n in body["agents"]]
        settings.desk_agents = desk_agents
        matrix = Matrix(
            w_momentum=m.get("w_momentum", 0.35),
            w_volume=m.get("w_volume", 0.25),
            w_overext=m.get("w_overext", 0.20),
            w_liquidity=m.get("w_liquidity", 0.20),
            min_momentum=m.get("min_momentum", 0.0015),
            max_momentum_1h=m.get("max_momentum_1h", 0.06),
            min_vol_surprise=m.get("min_vol_surprise", 1.5),
            min_quote_volume=m.get("min_quote_volume", 5_000_000.0),
            pass_threshold=m.get("pass_threshold", 0.62),
        )
        return settings, matrix


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def safe(d: dict[str, Any], key: str, default=None) -> Any:
    v = d.get(key, default)
    return v if v not in (None, "N/A") else default
