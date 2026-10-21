"""Phase C — couche Solana EN LECTURE SEULE, structurée.

Contrats (docs/DATA_FLOW.md, section esquisse) :
1. chaque observation porte sa source et son epoch (`Observation.name/ts`) ;
2. None ≠ 0 — une valeur inconnue est `None`/absente, jamais un zéro inventé ;
3. détection de péremption par TTL (`Observation.stale/usable`) — le consommateur
   décide du seuil, le blocage d'évaluation est SA politique ;
4. lecture seule : JSON-RPC/GET publics, aucune clé signée, aucun verbe
   d'exécution (guard testé) ;
5. endpoints publics documentés uniquement (RPC Solana + API Jupiter) — AUCUNE
   supposition GMGN (pas d'appel non documenté).

Le provider est consommé par `whale.snapshot(..., provider=…)` (option
`--offline` du CLI, mode offline explicite) — pas du code mort.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Observation:
    """Une donnée on-chain avec provenance et horodatage (contrat n°1/2/3)."""

    name: str                      # source : "solana-rpc", "jupiter", "cex", "offline"
    ts: float                      # epoch UTC de l'observation (0 = inconnu)
    value: Any                     # None = donnée ABSENTE (jamais un zéro de secours)
    ok: bool = True                # False = source ou requête indisponible
    note: str | None = None        # contexte d'écart/dégradation, purement informatif

    def age(self, now: float) -> float | None:
        if self.ts <= 0.0 or self.ts > now + 300.0:
            return None            # ts inconnu/invalide (même sémantique que B2)
        return max(0.0, now - self.ts)

    def stale(self, now: float, ttl: float) -> bool:
        """Périmée si ts inconnu ou âge > TTL (contrat n°3 : appels bloqués)."""
        a = self.age(now)
        return a is None or a > ttl

    def usable(self, now: float, ttl: float) -> bool:
        return self.ok and not self.stale(now, ttl)


@dataclass
class Balance:
    """Solde d'un wallet surveillé — lecture seule; -1 = RPC indisponible (hérité)."""

    wallet: str
    sol: float                     # -1 = indisponible (discipline héritée de whale.py)
    tokens: int                    # -1 = indisponible


class SolanaDataProvider(Protocol):
    """Interface lecture-seule (esquisse DATA_FLOW :86). Toutes les méthodes
    peuvent renvoyer une Observation ok=False plutôt que lever — l'appelant
    tranche la politique de dégradation."""

    def mint_info(self, mint: str) -> Observation:
        """supply/decimals/autorités {...} | ok=False."""
        ...

    def largest_holders(self, mint: str, top: int = 20) -> Observation:
        """list[{address, amount}] | None (endpoint lourd refusé → None, jamais [])."""
        ...

    def price(self, mint: str) -> Observation:
        """prix USD {value} depuis Jupiter puis CEX ; None si aucune source."""
        ...

    def watch(self, addresses: list[str]) -> list[Balance]:
        ...


class RpcProvider:
    """Provider LIVE en lecture seule — délègue aux primitives éprouvées de
    whale.py (RPC publics + clé gratuite optionnelle `AIDESK_RPC_URL` en tête)."""

    def __init__(self, price_symbol: str | None = None) -> None:
        # import local : éviter tout cycle à l'import (whale → solana → whale)
        from . import whale as _w
        self._w = _w
        self.price_symbol = price_symbol

    def mint_info(self, mint: str) -> Observation:
        try:
            info = self._w.mint_info(mint)
            return Observation("solana-rpc", time.time(), info,
                               note="getAccountInfo (SPL mint)")
        except Exception as e:
            return Observation("solana-rpc", time.time(), None, ok=False,
                               note=f"{type(e).__name__}: {e}"[:140])

    def largest_holders(self, mint: str, top: int = 20) -> Observation:
        try:
            holders = self._w.largest_holders(mint, top)
            return Observation("solana-rpc", time.time(), holders or None,
                               note="getTokenLargestAccounts")
        except Exception as e:
            # endpoint lourd refusé → ABSENT (None), pas une liste vide ni zéro
            return Observation("solana-rpc", time.time(), None, ok=False,
                               note=f"{type(e).__name__}: {e}"[:140])

    def price(self, mint: str) -> Observation:
        px, src, note = self._w.price_jupiter(mint), "jupiter", None
        if px is None:
            px = self._w.price_ccxt(self.price_symbol)
            src = "cex" if px is not None else "none"
        if px is None:
            return Observation(src, time.time(), None, ok=False,
                               note="prix indisponible (Jupiter puis CEX absents)")
        return Observation(src, time.time(), px,
                           note=None if src == "jupiter" else "fallback CEX")

    def watch(self, addresses: list[str]) -> list[Balance]:
        rows = self._w.watch_balances(addresses)
        return [Balance(r["wallet"], r["sol"], r["tokens"]) for r in rows]


class OfflineProvider:
    """Mode offline EXPLICITE — zéro réseau, zéro valeur inventée (contrat n°2).
    Toute requête rend une Observation ok=False, value=None, source='offline'."""

    def __init__(self, price_symbol: str | None = None) -> None:
        self.price_symbol = price_symbol

    def mint_info(self, mint: str) -> Observation:
        return Observation("offline", time.time(), None, ok=False,
                           note="mode offline explicite")

    def largest_holders(self, mint: str, top: int = 20) -> Observation:
        return Observation("offline", time.time(), None, ok=False,
                           note="mode offline explicite")

    def price(self, mint: str) -> Observation:
        return Observation("offline", time.time(), None, ok=False,
                           note="mode offline explicite")

    def watch(self, addresses: list[str]) -> list[Balance]:
        return [Balance(a, -1.0, -1) for a in addresses]


def resolve_provider(offline: bool | None = None,
                     price_symbol: str | None = None) -> SolanaDataProvider:
    """Sélection explicite : offline=True force OfflineProvider ; sinon
    `AIDESK_SOLANA=offline` (env) force aussi offline ; défaut : RpcProvider
    (lecture seule, RPC publics). Aucune déduction implicite ailleurs."""
    if offline or os.getenv("AIDESK_SOLANA", "").lower() == "offline":
        return OfflineProvider(price_symbol)
    return RpcProvider(price_symbol)
