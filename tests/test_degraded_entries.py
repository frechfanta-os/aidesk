"""Tests B7 — feed dégradé : rétablissement réseau + blocage des entrées.

Reproduction du défaut de production (2026-10-22) : 2 échecs réseau → flip
offline muet → random walk avec ts=now fraîchement forgé → le radar B2 passe
(trades 'offline' 24-30 sur la banque réelle) → jamais retour au live.

Isolation complète : monkeypatch.chdir(tmp_path) — state.json/DB du desk réels
jamais touchés (convention des tests existants).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.config import Matrix, Settings  # noqa: E402
from aidesk.market.feed import Feed         # noqa: E402
from aidesk.runtime import Desk             # noqa: E402


def fresh_feat(sym: str = "Y/USDT") -> Features:
    """Observation utilisable (fraîche, prefilter mom/vol/qv passés) — type B2."""
    from aidesk.types import Features
    return Features(sym, 100.0, 99.9, 100.1, 6e6, 0.004, 0.02, 2.0, 0.5,
                    True, time.time())


def make_desk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                      # isolement complet
    d = Desk(Settings(), Matrix(), offline=True,    # construction démo…
             db_path="a.db", jsonl="e.jsonl")
    d.feed.refresh = MagicMock(return_value={        # …pipée comme dégradé-réseau
        fresh_feat().symbol: fresh_feat()})
    d._manage_positions = MagicMock(return_value=[])
    return d


# --- 1. rétablissement du feed --------------------------------------------------

def test_reseau_retabli_apres_deux_echecs():
    f = Feed(offline=False)
    f.ex = MagicMock(name="ccxt-binance")
    f.ex.fetch_tickers.side_effect = [RuntimeError("boom1"),
                                      RuntimeError("boom2"),           # flip
                                      {"BTC/USDT": {"last": "82000",
                                                    "quoteVolume": 2e9,
                                                    "percentage": 0.5,
                                                    "high": 82100,
                                                    "low": 81900}}]    # recovery
    f.refresh(40, min_interval=0)
    assert f.offline is True                          # 2 échecs → dégradé
    out = f.refresh(40, min_interval=0)               # cycle suivant → retente
    assert f.offline is False                         # default rétabli SANS restart
    assert abs(out["BTC/USDT"].last - 82000) < 1      # VRAI prix, pas du random


def test_demo_explicite_reste_demo_sans_ex():
    f = Feed(offline=True)                            # --offline CLI : ex=None
    f.refresh(40, min_interval=0)
    assert f.offline is True and f.ex is None         # jamais de réseau silencieux


# --- 2. la porte dégradée bloques les entrées, pas la gestion --------------------

def test_degrade_bloque_entrees_et_continue_gestion(tmp_path, monkeypatch):
    d = make_desk(tmp_path, monkeypatch)
    d.feed.offline = True                             # flip réseau autonome
    d.feed.explicit = False                           # ≠ démo CLI
    d.radar.scan = MagicMock()
    d.research.decide = MagicMock()
    d.execd.try_entry = MagicMock()
    d.risk.check_treasury_freeze = MagicMock()
    d.tick(quiet=True)
    assert not d.radar.scan.called                    # ZÉRO nouveau candidat
    assert not d.research.decide.called
    assert not d.execd.try_entry.called
    assert d._manage_positions.called                 # SL/TP continuent
    assert d.risk.check_treasury_freeze.called        # gel B4 continue


def test_demo_explicite_garde_son_role_de_test(tmp_path, monkeypatch):
    """--offline est un mode de test assumé : radar actif (entrées démo possibles)."""
    d = make_desk(tmp_path, monkeypatch)
    d.feed.offline = True
    d.feed.explicit = True
    d.radar.scan = MagicMock(return_value=[])
    d.tick(quiet=True)
    assert d.radar.scan.called                        # contrat préservé


# --- 3. transitions observables (le flip muet ne l'est plus) ---------------------

def test_transitions_emettent_feed_degrade_et_recover(tmp_path, monkeypatch):
    d = make_desk(tmp_path, monkeypatch)
    d.radar.scan = MagicMock(return_value=[])         # zéro event parasite
    kinds: list[str] = []
    d.store.add_event = lambda kind, payload: kinds.append(kind)
    d.tick(quiet=True)                                # boot : balise None → muet
    assert kinds == []
    d.feed.offline = False
    d.tick(quiet=True)                                # True→False
    d.feed.offline = True
    d.tick(quiet=True)                                # False→True
    assert kinds == ["feed_recover", "feed_degrade"]
