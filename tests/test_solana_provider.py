"""Tests Phase C — couche Solana en lecture seule.

Aucun test ne touche le réseau : RPC mocké via monkeypatch des primitives
whale.py, provider factice pour le bout-en-bout snapshot. Garanties testées :
None ≠ 0, provenance ts/source sur chaque observation, TTL (péremption),
mode offline explicite sans valeur inventée, AUCUN verbe d'exécution
(guard permanent sur les sources).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.market import whale          # noqa: E402
from aidesk.market.solana import (       # noqa: E402
    Balance, Observation, OfflineProvider, RpcProvider, resolve_provider,
)

NOW = time.time()   # référence lente : les tests py utilisent leur propre now courant
MINT = "TESTMINT1111111111111111111111111111111111"


# 1 — sélection de provider : explicite, jamais implicite ------------------------

def test_defaut_rpc_offline_force_par_arg():
    assert isinstance(resolve_provider(), RpcProvider)
    assert isinstance(resolve_provider(offline=True), OfflineProvider)


def test_offline_force_par_env(monkeypatch):
    monkeypatch.setenv("AIDESK_SOLANA", "offline")
    assert isinstance(resolve_provider(), OfflineProvider)
    monkeypatch.setenv("AIDESK_SOLANA", "LIVE")          # valeur non reconnue → live
    assert isinstance(resolve_provider(), RpcProvider)
    monkeypatch.delenv("AIDESK_SOLANA")


# 2 — sémantique offline : absent ≠ zéro -----------------------------------------

def test_offline_provider_ne_invente_rien():
    p = OfflineProvider()
    for obs in (p.mint_info(MINT), p.largest_holders(MINT), p.price(MINT)):
        assert obs.ok is False and obs.value is None      # None ≠ 0
        assert obs.name == "offline"
    rows = p.watch(["W1", "W2"])
    assert all(isinstance(r, Balance) and r.sol == -1.0 and r.tokens == -1
               for r in rows)                             # marqueurs hérités explicites


# 3 — RpcProvider : adapter sur les primitives, dégradation propre ----------------

def test_rpc_mint_info_ok_avec_provenance(monkeypatch):
    fake = {"supply": 10 ** 9, "decimals": 6, "mint_authority": False,
            "freeze_authority": False}
    monkeypatch.setattr(whale, "mint_info", lambda m: fake, raising=False)
    obs = RpcProvider().mint_info(MINT)
    now = time.time()
    assert obs.ok and obs.value is fake and obs.name == "solana-rpc"
    assert obs.age(now) is not None and obs.age(now) < 60   # ts est un epoch réel


def test_rpc_largest_holders_erreur_vaut_absent_pas_liste_vide(monkeypatch):
    def boom(m, top=20):
        raise whale.WhaleError("endpoint lourd refusé (403)")
    monkeypatch.setattr(whale, "largest_holders", boom, raising=False)
    obs = RpcProvider().largest_holders(MINT)
    assert obs.ok is False and obs.value is None          # ABSENT, jamais []
    assert "403" in (obs.note or "")


def test_rpc_price_chain_jupiter_puis_cex(monkeypatch):
    w = whale
    p = RpcProvider()
    monkeypatch.setattr(w, "price_jupiter", lambda m: 0.000123, raising=False)
    assert p.price(MINT).name == "jupiter" and p.price(MINT).value == 0.000123
    monkeypatch.setattr(w, "price_jupiter", lambda m: None, raising=False)
    monkeypatch.setattr(w, "price_ccxt", lambda s: 0.000121, raising=False)
    obs = p.price(MINT)
    assert obs.name == "cex" and "fallback" in (obs.note or "")  # écart journalisé
    monkeypatch.setattr(w, "price_ccxt", lambda s: None, raising=False)
    obs = p.price(MINT)
    assert obs.ok is False and obs.value is None


# 4 — TTL / péremption (contrat n°3 : évaluations bloquées) ----------------------

def test_observation_stale_et_usable():
    fresh = Observation("solana-rpc", NOW - 10, {"supply": 1})
    old = Observation("solana-rpc", NOW - 4000, {"supply": 1})
    unknown_ts = Observation("solana-rpc", 0.0, None)
    assert fresh.usable(NOW, ttl=300) and not fresh.stale(NOW, 300)
    assert not old.usable(NOW, ttl=300) and old.stale(NOW, 300)
    assert not unknown_ts.usable(NOW, ttl=300) and unknown_ts.stale(NOW, 300)
    bad = Observation("solana-rpc", NOW - 10, None, ok=False)
    assert not bad.usable(NOW, ttl=300)                   # ok=False → jamais utile


# 5 — guard lecture-seule permanent (aucun verbe d'exécution) ---------------------def test_guard_lecture_seule_sources():
    forbidden = ("sendtransaction", "signtransaction", "requestairdrop",
                 "signer", "keypair", "privatekey", "getblockcommitment")
    for rel in ("aidesk/market/whale.py", "aidesk/market/solana.py",
                "tools/whale_scan.py"):
        src = Path(PROJECT / rel).read_text().lower()
        hit = [w for w in forbidden if w in src]
        assert hit == [], f"{rel} contient un verbe d'exécution : {hit}"


# 6 — bout-en-bout snapshot AVEC provider factice (aucun réseau) -------------------

class _FakeProvider:
    """Provider déterministe de test (pas le réseau)."""

    def __init__(self, holders_pct=0.30, authority=False, px=0.5):
        self.holders_pct = holders_pct
        self.authority = authority
        self.px = px

    def mint_info(self, mint):
        return Observation("fake-rpc", time.time(),
                           {"supply": 1_000_000 * 10 ** 9, "decimals": 9,
                            "mint_authority": self.authority,
                            "freeze_authority": self.authority})

    def largest_holders(self, mint, top=20):
        if self.holders_pct is None:
            return Observation("fake-rpc", time.time(), None, ok=False,
                               note="endpoint refusé")
        s = 1_000_000                                       # supply en unités humaines
        rows = [{"address": f"H{i}", "amount": self.holders_pct * s / 10}
                for i in range(10)]                         # top10 = holders_pct exact
        rows += [{"address": f"H{i}", "amount": 0.0001 * s / max(1, top - 10)}
                 for i in range(10, top)]                   # queue négligeable
        return Observation("fake-rpc", time.time(), rows)

    def price(self, mint):
        return Observation("cex", time.time(), self.px, note="fallback CEX")

    def watch(self, addresses):
        return [Balance(a, 1.0, 5) for a in addresses]


def test_snapshot_consomme_le_provider_verdict_concentre(tmp_path):
    db = str(tmp_path / "w.db")
    snap = whale.snapshot(MINT, db=db, provider=_FakeProvider(holders_pct=0.60))
    assert snap["verdict"].startswith("CONCENTRÉ")        # top10 60 % > 55 %
    assert snap["price"] == 0.5 and snap["top10_pct"] == 0.6
    assert whale.previous(MINT, db) == 0.6                # persistance intacte


def test_snapshot_verdict_rug_et_mouvement(tmp_path):
    db = str(tmp_path / "wr.db")
    r = whale.snapshot(MINT, db=db, provider=_FakeProvider(holders_pct=0.40,
                                                           authority=True))
    assert r["verdict"].startswith("RUG-RISK")
    assert r["price"] == 0.5
    r2 = whale.snapshot(MINT, db=db, provider=_FakeProvider(holders_pct=0.55))
    assert r2["verdict"].startswith("MOUVEMENT WHALE")    # Δ +15 pts > 10 pts
    r3 = whale.snapshot(MINT, db=db, provider=_FakeProvider(holders_pct=0.55))
    assert r3["verdict"].startswith("OBSERVATION")        # Δ 0 pt : distribution normale


def test_snapshot_partiel_quand_l_endpoint_lourd_refusé(tmp_path):
    db = str(tmp_path / "wp.db")
    snap = whale.snapshot(MINT, db=db,
                          provider=_FakeProvider(holders_pct=None))
    assert snap["verdict"].startswith("PARTIEL")          # endpoint lourd absent
    assert snap["holders"] == [] and snap["top10_pct"] is None
    assert snap["price"] == 0.5                           # légère seule disponible
    fe = whale.features_for_research(snap)
    assert fe["whale_known"] is False and fe["whale_top10_pct"] is None  # None ≠ 0


def test_snapshot_offline_leve_WhaleError(tmp_path):
    """Offline explicite : mint_info absent → WhaleError (CLI : « ÉCHEC »), pas d'invention."""
    with pytest.raises(whale.WhaleError):
        whale.snapshot(MINT, db=str(tmp_path / "we.db"),
                       provider=OfflineProvider())
