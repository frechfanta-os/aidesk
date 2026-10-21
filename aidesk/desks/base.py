from __future__ import annotations

from dataclasses import dataclass


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


@dataclass
class Agent:
    """One seat on a desk. The head can promote (budget) or fire (rev bump)."""

    name: str
    desk: str
    budget: float = 1.0
    score: float = 0.50
    wins: int = 0
    losses: int = 0
    trades_credited: int = 0
    rev: str = "v1"
    last_fired: float = 0.0

    def credit_win(self, _pnl: float) -> None:
        self.wins += 1
        self.trades_credited += 1
        self.score = self._rescore()

    def credit_loss(self, _pnl: float) -> None:
        self.losses += 1
        self.trades_credited += 1
        self.score = self._rescore()

    def _rescore(self) -> float:
        s = 0.5 + 0.10 * self.wins - 0.15 * self.losses
        return round(min(0.95, max(0.10, s)), 3)

    def fire(self, now: float) -> str:
        old = self.rev
        n = int(old[1:]) + 1
        self.rev = f"v{n}"
        self.wins = 0
        self.losses = 0
        self.trades_credited = 0
        self.score = 0.50
        self.last_fired = now
        return old


def roster(desk_names: dict[str, list[str]]) -> list[Agent]:
    out: list[Agent] = []
    for desk, names in desk_names.items():
        for n in names:
            out.append(Agent(name=n, desk=desk))
    return out
