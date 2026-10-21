from __future__ import annotations

from .base import Agent


class HeadOffice:
    """GROK CORE: hourly review — promote the best budget, fire the rotten seat."""

    def __init__(self, settings, store) -> None:
        self.s = settings
        self.store = store
        self.logs: list[str] = []
        self.promotions = 0
        self.firings = 0

    def review(self, agents: list[Agent], now: float) -> None:
        self.logs = []
        eligible = [a for a in agents if a.trades_credited >= 4]
        if not eligible:
            return
        best = max(eligible, key=lambda a: a.score)
        if best.score >= 0.65 and best.budget < 1.8:
            best.budget = round(best.budget + 0.2, 2)
            self.promotions += 1
            line = (f"PROMOTION {best.name} ({best.desk}) → budget ×{best.budget:g} "
                    f"(score {best.score:.2f}, {best.wins}W/{best.losses}L)")
            self.logs.append(line)
            self.store.add_event("head_review", {"line": line})
        worst = min(eligible, key=lambda a: a.score)
        if (worst.score < self.s.fires_below
                and (now - worst.last_fired) > self.s.cooldown_h * 3600):
            old = worst.fire(now)
            self.firings += 1
            line = (f"LICENCIEMENT {worst.name} ({worst.desk}) {old} → {worst.rev} "
                    f"(score {worst.score:.2f}) — reprogrammation par AUDIT")
            self.logs.append(line)
            self.store.add_event("head_review", {"line": line})
