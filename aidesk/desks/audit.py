from __future__ import annotations

from ..types import Trade


class AuditDesk:
    """Post-mortem of every closed trade; tightens/relaxes the matrix in-clamps."""

    def __init__(self, matrix, store) -> None:
        self.m = matrix
        self.store = store
        self.postmortems = 0
        self.wins_since_relax = 0

    def on_close(self, trade: Trade) -> str:
        age = (trade.ts_close - trade.ts_open) / 60.0
        kind = "GAIN" if trade.pnl > 0 else "PERTE"
        note = (
            f"{kind} {trade.symbol} {trade.pnl:+.4f} $ en {age:.0f} min | {trade.reason} | "
            f"mom15@entrée {trade.features.mom_15m * 100:+.2f} % | "
            f"vol ×{trade.features.vol_surprise:.1f} | agent {trade.agent}"
            f"/{trade.approver or '—'}"
        )
        self.postmortems += 1
        self.store.add_event("postmortem", {"note": note, "pnl": trade.pnl,
                                            "reason": trade.reason})
        if trade.pnl <= 0:
            if trade.reason == "SL":
                self.m.tighten(f"SL {trade.symbol} → serrage",
                               min_vol_surprise=0.05, pass_threshold=0.004)
            else:  # TIMEOUT / MANUAL / perte lente
                self.m.tighten(f"{trade.reason} {trade.symbol} → serrage momentum",
                               min_momentum=0.0002, pass_threshold=0.002)
            self.store.add_matrix(self.m.revisions,
                                  f"rev{self.m.revisions}: serrage après {trade.reason} {trade.symbol}")
            self.wins_since_relax = 0
        elif trade.reason == "TP":
            self.wins_since_relax += 1
            if self.wins_since_relax >= 3:
                self.wins_since_relax = 0
                self.m.relax("3 TP consécutifs → léger desserrage",
                             pass_threshold=-0.002, min_vol_surprise=-0.05)
                self.store.add_matrix(self.m.revisions,
                                      f"rev{self.m.revisions}: desserrage après série de TP")
        return note
