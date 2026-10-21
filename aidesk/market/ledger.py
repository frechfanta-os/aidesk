from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ledger:
    start_usdt: float
    wallet_usdt: float = 0.0
    vault_usdt: float = 0.0
    trades: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.wallet_usdt = self.start_usdt

    @property
    def net_usdt(self) -> float:
        return round(self.wallet_usdt + self.vault_usdt, 4)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def loss_cost(self) -> float:
        return round(-sum(t.pnl for t in self.trades if t.pnl <= 0), 4)

    def sweep(self, keep: float) -> float:
        excess = max(0.0, self.wallet_usdt - keep)
        move = round(excess * 0.5, 4)
        self.wallet_usdt -= move
        self.vault_usdt += move
        return move
