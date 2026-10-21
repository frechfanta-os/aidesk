from __future__ import annotations

import json
import os
import time
from typing import Any

from .config import Settings, fmt_usd, now_iso
from .desks import (Agent, AuditDesk, ExecutionDesk, HeadOffice, Radar, Research,
                    RiskAgent, roster, TreasuryDesk)
from .llm import has_key
from .market import Feed, Ledger, PaperBroker
from .store import Store
from .types import Features, Position, Trade

DESK_NAMES: dict[str, list[str]] = {
    "radar": ["SCOUT", "FEED", "SIGNAL"],
    "research": ["MEMORY", "MEMORY-2"],
    "execution": ["EXEC", "SNIPER", "ROUTER", "AGENT-01", "AGENT-02", "AGENT-03"],
    "audit": ["HEDGE", "AUDIT-2"],
    "treasury": ["VAULT"],
}


class Desk:
    """Glue: data feed → radar → research → risk/execution → audit → head."""

    def __init__(self, settings: Settings, matrix, offline: bool = False,
                 db_path: str = "aidesk.db", jsonl: str = "events.jsonl") -> None:
        self.s = settings
        self.m = matrix
        self.store = Store(db_path, jsonl)
        self.ledger = Ledger(settings.start_usdt)
        self.broker = PaperBroker(self.ledger, settings)
        self.feed = Feed(offline=offline)
        src: dict[str, list[str]] = dict(DESK_NAMES)
        for desk, names in (getattr(self.s, "desk_agents", None) or {}).items():
            if names:
                src[desk] = list(names)
        self.agents = roster(src)
        self.by_name: dict[str, Agent] = {a.name: a for a in self.agents}
        self.radar = Radar(self._desk("radar"), fresh_s=settings.freshness_s)
        self.research = Research(self._desk("research"), matrix, self.store)
        self.risk = RiskAgent(settings, self.ledger)
        self.execd = ExecutionDesk(self._desk("execution"), self.broker, self.risk, self.store)
        self.audit = AuditDesk(matrix, self.store)
        self.treasury = TreasuryDesk(settings, self.ledger, self.risk, self.store)
        self.head = HeadOffice(settings, self.store)
        self.ctl = "ctl"
        os.makedirs(self.ctl, exist_ok=True)
        # B5 : provenance de session — utilisée par store.add_trade ; le mode
        # reflète l'état RÉEL du feed (--offline explicite ou bascule offline),
        # jamais un nom de processus.
        self.store.mode = "offline" if (offline or self.feed.offline) else "live"
        self.last_feats: dict[str, Any] = {}
        self.paused = False
        self.stop = False
        self.ticks = 0
        self._quiet = False
        self._closed = False
        self._restore()

    def _desk(self, name: str) -> list[Agent]:
        return [a for a in self.agents if a.desk == name]

    # ------------------------------------------------------------ restore
    def _restore(self) -> None:
        """Re-hydrate le desk au boot.

        Trades clôturés : SQLite est la source de vérité (indépendante de state.json).
        Wallet/positions/agents/matrice : depuis state.json (snapshot du dernier tick).
        Sans state.json ni base : no-op (démarrage à neuf)."""
        try:
            with open("state.json", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = None
        if data is not None and not (data.get("ledger") or data.get("agents")):
            data = None
        # 1) trades clôturés — TOUJOURS tenté depuis la base
        for tr in self.store.all_trades():
            f = Features(tr["symbol"], float(tr.get("exit") or 0), None, None,
                         0.0, 0.0, 0.0, 0.0, 0.0)
            self.ledger.trades.append(Trade(
                symbol=tr["symbol"], entry=float(tr["entry"]), exit=float(tr["exit"]),
                qty=float(tr["qty"]), pnl=float(tr["pnl"]),
                reason=str(tr.get("reason") or ""),
                ts_open=float(tr.get("ts_open") or 0),
                ts_close=float(tr.get("ts_close") or 0),
                agent=str(tr.get("agent") or ""), approver=tr.get("approver"),
                score=float(tr.get("score") or 0.0), features=f))
        n_trades = len(self.ledger.trades)
        # 2) le reste de l'état vivant dépend de state.json
        if data is None:
            return
        led = data["ledger"] or {}
        self.ledger.start_usdt = float(led.get("start_usdt") or self.ledger.start_usdt)
        self.ledger.wallet_usdt = float(led.get("wallet_usdt", self.ledger.wallet_usdt))
        self.ledger.vault_usdt = float(led.get("vault_usdt", 0.0))
        self.broker.fees_paid = float(led.get("fees_paid", 0.0))
        # agents (budget/score/W-L/rev)
        for a in (data.get("agents") or []):
            ag = self.by_name.get(str(a.get("name", "")))
            if not ag:
                continue
            try:
                ag.budget = min(1.8, max(1.0, float(a.get("budget", 1.0))))
                ag.wins = int(a.get("wins", 0))
                ag.losses = int(a.get("losses", 0))
                ag.rev = str(a.get("rev") or "v1")
                ag.trades_credited = ag.wins + ag.losses
                ag.score = ag._rescore()
            except Exception:
                continue
        # matrice (seuils mutés par AUDIT)
        mx = data.get("matrix") or {}
        try:
            self.m.pass_threshold = float(mx.get("pass_threshold", self.m.pass_threshold))
            self.m.min_momentum = float(mx.get("min_momentum", self.m.min_momentum))
            self.m.min_vol_surprise = float(mx.get("min_vol_surprise", self.m.min_vol_surprise))
            self.m.max_momentum_1h = float(mx.get("max_momentum_1h", self.m.max_momentum_1h))
            self.m.revisions = int(mx.get("revisions", self.m.revisions))
        except Exception:
            pass
        # positions ouvertes
        restored_positions = 0
        for p in (data.get("positions") or []):
            try:
                f = Features(str(p["symbol"]), float(p.get("entry") or 0), None, None,
                             0.0, 0.0, 0.0, 0.0, 0.0)
                self.broker.open[str(p["symbol"])] = Position(
                    symbol=str(p["symbol"]), entry=float(p["entry"]),
                    qty=float(p["qty"]), usdt=float(p["usdt"]),
                    ts_open=float(p.get("ts_open") or time.time()),
                    agent=str(p.get("agent") or ""), approver=p.get("approver"),
                    features=f, score=float(p.get("score") or 0.0))
                restored_positions += 1
            except Exception:
                continue
        self.store.add_event("restore", {"positions": restored_positions,
                                         "trades": n_trades})
        if not self._quiet and (restored_positions or n_trades):
            print(f"    restauré : wallet {fmt_usd(self.ledger.wallet_usdt)} | "
                  f"{restored_positions} position(s) | "
                  f"{n_trades} trade(s) clôturé(s) (SQLite) | "
                  f"matrice rev {self.m.revisions}")

    # ------------------------------------------------------------------ run
    def run(self, hours: float | None, tick_seconds: float = 60.0,
            quiet: bool = False) -> None:
        self._quiet = quiet
        connected = self.feed.connect()
        if not connected:
            self.feed.offline = True
        mode = "OFFLINE (démo, random walk)" if self.feed.offline else f"ccxt:{self.feed.name}"
        llm_on = has_key()
        self.store.add_event("boot", {"mode": mode, "llm": llm_on,
                                      "start_usdt": self.ledger.start_usdt})
        if not quiet:
            print(f"=== AIDESK — desk multi-agents === mode {mode} | LLM "
                  f"({'actif' if llm_on else 'hors (thèse déterministe)'}) | "
                  f"banque {fmt_usd(self.ledger.start_usdt)}")
            print(f"    agents {'/'.join(a.name for a in self.agents)}")
        t0 = time.time()
        next_hour = t0 + 3600.0
        while not self.stop:
            tick_start = time.time()
            self.tick(quiet)
            if hours is not None and (time.time() - t0) >= hours * 3600:
                break
            if time.time() >= next_hour:
                self.hourly(quiet)
                next_hour += 3600.0
            reste = tick_seconds - (time.time() - tick_start)
            if reste > 0:
                try:
                    time.sleep(reste)
                except KeyboardInterrupt:
                    break
        self.final_report()

    # ------------------------------------------------------------------ tick
    def tick(self, quiet: bool) -> None:
        self._controls(quiet)
        if self.stop:
            return
        now = time.time()
        feats = self.feed.refresh(self.s.top_n)
        self.last_feats.update(feats)
        # B5 : si le feed a basculé offline (2 échecs réseau), le mode suit l'état
        # réel des données — les trades de démo seront étiquetés 'offline'.
        self.store.mode = "offline" if self.feed.offline else "live"
        closes = self._manage_positions(feats, now)
        signals = 0
        decisions = 0
        entries = 0
        if not self.paused:
            self.risk.check_treasury_freeze()   # B4 : gel évalué à CHAQUE tick
                                                # (précédemment 1×/h → latence jusqu'à 1 h)
            sigs = self.radar.scan(feats, set(self.broker.open), now,
                                   self.m.min_quote_volume)
            signals = len(sigs)
            for sig in sigs:
                d = self.research.decide(sig, now)
                decisions += 1
                if d.verdict:
                    if self.execd.try_entry(sig.features, d, now):
                        entries += 1
        if not quiet:
            L = self.ledger
            tag = " [PAUSE]" if self.paused else ""
            print(f"[{now_iso()}] sig={signals} dec={decisions} ent={entries} "
                  f"cls={closes}{tag} | bank {fmt_usd(L.wallet_usdt)} "
                  f"vault {fmt_usd(L.vault_usdt)} net {fmt_usd(L.net_usdt)} "
                  f"({L.wins}/{L.losses})")
        self.ticks += 1
        self._snapshot()

    def _equity_series(self) -> list[float]:
        eq: list[float] = []
        prev = self.ledger.start_usdt
        for t in self.ledger.trades:
            prev += t.pnl
            eq.append(round(prev, 2))
        return eq

    def _snapshot(self) -> None:
        """Write state.json for the web dashboard (atomic replace, never fatal)."""
        try:
            data: dict[str, Any] = {
                "ts": now_iso(),
                "ticks": self.ticks,
                "paused": self.paused,
                "feed": {"offline": self.feed.offline, "name": self.feed.name,
                         "ts": self.feed.last_ts() or None,
                         "age_s": (round(time.time() - self.feed.last_ts())
                                   if self.feed.last_ts() else None)},
                "ledger": {
                    "start_usdt": self.ledger.start_usdt,
                    "wallet_usdt": round(self.ledger.wallet_usdt, 4),
                    "vault_usdt": round(self.ledger.vault_usdt, 4),
                    "fees_paid": round(self.broker.fees_paid, 4),
                    "mtm_usdt": self.unrealized(),
                    "wins": self.ledger.wins,
                    "losses": self.ledger.losses,
                    "equity": [round(self.ledger.start_usdt, 2)] + self._equity_series(),
                },
                "positions": [
                    {
                        "symbol": sym,
                        "entry": p.entry,
                        "qty": p.qty,
                        "usdt": p.usdt,
                        "agent": p.agent,
                        "approver": p.approver,
                        "score": p.score,
                        "ts_open": p.ts_open,
                        "age_min": round((time.time() - p.ts_open) / 60.0, 1),
                        "last": (f.last if (f := self.last_feats.get(sym)) else p.entry),
                    }
                    for sym, p in self.broker.open.items()
                ],
                "trades_closed": [
                    {"symbol": t.symbol, "entry": t.entry, "exit": t.exit,
                     "qty": t.qty, "pnl": t.pnl, "reason": t.reason,
                     "ts_open": t.ts_open, "ts_close": t.ts_close,
                     "agent": t.agent, "approver": t.approver, "score": t.score}
                    for t in self.ledger.trades[-500:]
                ],
                "agents": [
                    {
                        "name": a.name,
                        "desk": a.desk,
                        "budget": a.budget,
                        "score": a.score,
                        "wins": a.wins,
                        "losses": a.losses,
                        "rev": a.rev,
                    }
                    for a in self.agents
                ],
                "matrix": {
                    "pass_threshold": self.m.pass_threshold,
                    "min_momentum": self.m.min_momentum,
                    "min_vol_surprise": self.m.min_vol_surprise,
                    "max_momentum_1h": self.m.max_momentum_1h,
                    "revisions": self.m.revisions,
                },
                "risk": {
                    "blocks": self.risk.blocks,
                    "day_pnl": round(self.risk.day_pnl, 4),
                    "day_frozen": self.risk.day_frozen,
                    "frozen_treasury": self.risk.frozen_treasury,
                },
                "counters": {
                    "signals": self.radar.signals_emitted,
                    "decisions": self.research.decisions_made,
                    "entries": self.execd.entries_made,
                    "postmortems": self.audit.postmortems,
                    "promotions": self.head.promotions,
                    "firings": self.head.firings,
                },
            }
            tmp = "state.json.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, default=str)
            os.replace(tmp, "state.json")
        except Exception:
            pass

    # ------------------------------------------------- position management
    def _manage_positions(self, feats: dict, now: float) -> int:
        closed = 0
        for sym in list(self.broker.open):
            f = feats.get(sym) or self._lookup(sym)
            if f is None:
                continue
            pos = self.broker.open[sym]
            price = f.last if f.last > 0 else pos.entry
            hit = self.broker.target_price(sym, price)
            reason = None
            if hit:
                reason, px = hit
            elif (now - pos.ts_open) / 60.0 >= self.s.max_hold_minutes:
                reason, px = "TIMEOUT", price
            if reason:
                trade = self.broker.settle(f, pos, px, reason)
                self.store.add_trade(trade)
                self.audit.on_close(trade)
                self.risk.on_close(trade.pnl)
                self._credit(trade)
                closed += 1
                self._print_closed(trade, reason)
        return closed

    def _lookup(self, sym: str):
        f = self.last_feats.get(sym)
        if f is not None:
            return f
        if self.feed.offline or self.feed.ex is None:
            return None
        try:
            t = self.feed.ex.fetch_ticker(sym)
            return self.feed.features_from_ticker(sym, t)
        except Exception:
            return None

    def _credit(self, trade) -> None:
        for name in {trade.agent, trade.approver}:
            if not name or name not in self.by_name:
                continue
            a = self.by_name[name]
            (a.credit_win if trade.pnl > 0 else a.credit_loss)(trade.pnl)

    def _print_closed(self, trade, reason: str) -> None:
        if not self._quiet:
            print(f"  [CLOSE] {trade.symbol} {reason} "
                  f"{trade.pnl:+.4f} $ (entry {trade.entry:.6g} → exit {trade.exit:.6g})")

    # ------------------------------------------------------------ controls
    def _controls(self, quiet: bool) -> None:
        kill = os.path.join(self.ctl, "KILL")
        if os.path.exists(kill):
            os.remove(kill)
            if not quiet:
                print("!! KILL — fermeture de toutes les positions puis arrêt.")
            self._force_close_all("KILL")
            self.stop = True
            return
        sellall = os.path.join(self.ctl, "SELL_ALL")
        if os.path.exists(sellall):
            os.remove(sellall)
            if not quiet:
                print("!! SELL_ALL — fermeture de toutes les positions (le desk continue).")
            self._force_close_all("SELL_ALL")
            self._snapshot()
        self.paused = os.path.exists(os.path.join(self.ctl, "PAUSE"))

    def _force_close_all(self, reason: str) -> None:
        now = time.time()
        for sym in list(self.broker.open):
            f = self.last_feats.get(sym) or self._lookup(sym)
            if f is None:
                continue
            pos = self.broker.open[sym]
            trade = self.broker.settle(f, pos, f.last if f.last > 0 else pos.entry, reason)
            self.store.add_trade(trade)
            self.audit.on_close(trade)
            self.risk.on_close(trade.pnl)
            self._credit(trade)
            self._print_closed(trade, reason)

    # -------------------------------------------------------------- hourly
    def hourly(self, quiet: bool) -> None:
        self.treasury.hour_tick()
        self.head.review(self.agents, time.time())
        if self.head.logs:
            self.store.add_event("head_review", {"logs": self.head.logs})
        if not quiet:
            self.hud()

    def hud(self) -> None:
        L, B = self.ledger, self.broker
        pnl = L.net_usdt - L.start_usdt
        wr = 100.0 * L.wins / max(1, L.wins + L.losses)
        print("\n──────── RAPPORT HORAIRE ────────")
        print(f"  banque {fmt_usd(L.wallet_usdt)} | vault {fmt_usd(L.vault_usdt)} | "
              f"net cash {fmt_usd(L.net_usdt)} | MTM ouvert ~{fmt_usd(self.unrealized())} "
              f"| PnL flottant {(self.unrealized() + L.wallet_usdt + L.vault_usdt - L.start_usdt):+.2f} $")
        print(f"  trades {L.wins + L.losses} (W {L.wins} / L {L.losses}) winrate "
              f"{wr:.0f} % | frais payés {fmt_usd(self.broker.fees_paid)}")
        if B.open:
            for sym, p in B.open.items():
                f = self.last_feats.get(sym)
                last = f.last if f else p.entry
                move = (last - p.entry) / p.entry * 100
                print(f"  OUVERT {sym} {fmt_usd(p.usdt)} @ {p.entry:.6g} "
                      f"→ {last:.6g} ({move:+.2f} %) agent {p.agent}")
        else:
            print("  positions ouvertes : aucune")
        print(f"  matrice: seuil {self.m.pass_threshold:.3f} | rev {self.m.revisions} | "
              f"desk: {self.execd.entries_made} entrées, {self.audit.postmortems} "
              f"post-mortems, {self.risk.blocks} blocages RISK")
        for line in self.head.logs:
            print(f"  {line}")
        print("───────────────────────────────────────\n")

    def unrealized(self) -> float:
        """Mark-to-market paper value of still-open positions."""
        total = 0.0
        for sym, p in self.broker.open.items():
            f = self.last_feats.get(sym)
            last = f.last if f and f.last > 0 else p.entry
            total += p.qty * last * (1 - self.s.fee_bps / 10_000)
        return round(total, 4)

    # ---------------------------------------------------------------- end
    def final_report(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._snapshot()
        L = self.ledger
        n = L.wins + L.losses
        wr = 100.0 * L.wins / max(1, n)
        mtm = self.unrealized()
        est_net = round(L.net_usdt + mtm, 4)
        pnl = est_net - L.start_usdt
        print("\n══════════ SCOREBOARD FINAL ══════════")
        print(f"  start {fmt_usd(L.start_usdt)} → net (est. MTM) {fmt_usd(est_net)} "
              f"(PnL {pnl:+.2f} $, {pnl / L.start_usdt * 100:+.2f} %)")
        print(f"  cash {fmt_usd(L.wallet_usdt)} | positions ouvertes valorisées "
              f"~{fmt_usd(mtm)} ({len(self.broker.open)}) | vault {fmt_usd(L.vault_usdt)}")
        print(f"  trades clôturés : {n} | W {L.wins} / L {L.losses} | winrate "
              f"{wr:.0f} % | frais {fmt_usd(self.broker.fees_paid)}")
        print(f"  matrice revisions {self.m.revisions} | post-mortems "
              f"{self.audit.postmortems} | blocages RISK {self.risk.blocks}")
        print("  détail DB : aidesk.db (trades, decisions, events) + events.jsonl")
        print("═══════════════════════════════════════")
        self.store.close()
