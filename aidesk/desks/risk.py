from __future__ import annotations

from datetime import datetime, timezone


class RiskAgent:
    """Deterministic veto. No LLM, no negotiation: caps, stops, freezes."""

    def __init__(self, settings, ledger) -> None:
        self.s = settings
        self.ledger = ledger
        self.entries: list[float] = []
        self.day: str = self._today()
        self.day_pnl = 0.0
        self.frozen_treasury = False
        self.blocks = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def day_frozen(self) -> bool:
        return self.day_pnl <= self.ledger.start_usdt * self.s.daily_loss_stop

    def allow(self, open_count: int, now: float) -> tuple[bool, str]:
        self._roll_day()
        if self.frozen_treasury:
            self.blocks += 1
            return False, "gel trésorerie"
        if self.day_frozen:
            self.blocks += 1
            return False, "stop journalier"
        if open_count >= self.s.max_open_positions:
            self.blocks += 1
            return False, f"max positions ({open_count})"
        self.entries = [t for t in self.entries if now - t < 3600.0]
        if len(self.entries) >= self.s.max_entries_per_hour:
            self.blocks += 1
            return False, "max entrées/h"
        if self.ledger.wallet_usdt < 1.0:
            self.blocks += 1
            return False, "portefeuille vide"
        return True, "OK"

    def note_entry(self, now: float) -> None:
        self.entries.append(now)

    def on_close(self, pnl: float) -> None:
        self._roll_day()
        self.day_pnl += pnl

    def check_treasury_freeze(self) -> None:
        net = self.ledger.net_usdt
        if net < self.ledger.start_usdt * self.s.freeze_below:
            self.frozen_treasury = True
        elif net >= self.ledger.start_usdt * 0.85:
            self.frozen_treasury = False

    def size_for(self, budget: float) -> float:
        return round(self.ledger.wallet_usdt * self.s.max_position_fraction * budget, 2)

    def _roll_day(self) -> None:
        today = self._today()
        if today != self.day:
            self.day = today
            self.day_pnl = 0.0
