from __future__ import annotations


class TreasuryDesk:
    """VAULT: freeze checks each hour, sweep of the excess every sweep_every_h."""

    def __init__(self, settings, ledger, risk, store) -> None:
        self.s = settings
        self.ledger = ledger
        self.risk = risk
        self.store = store
        self.hours = 0
        self.swept_total = 0.0

    def hour_tick(self) -> None:
        self.hours += 1
        self.risk.check_treasury_freeze()
        if self.hours >= self.s.sweep_every_h:
            self.hours = 0
            excess = self.ledger.wallet_usdt - self.ledger.start_usdt * 1.5
            if excess > 1.0:
                move = round(excess * 0.5, 2)
                self.ledger.vault_usdt += move
                self.ledger.wallet_usdt -= move
                self.swept_total += move
                self.store.add_event("sweep", {"moved": move})
