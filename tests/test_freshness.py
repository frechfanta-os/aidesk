"""Tests B2 — fraîcheur et qualité des Features (provenance + gate radar).

Familles couvertes : fraîche / périmée / absente / ts invalide / fraîcheur inconnue
(restore historique) / source indisponible + fallback offline / cohérence offline /
configuration du seuil. Aucune entrée ne doit être déclenchée sur données périmées
ou non datées.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.config import Settings        # noqa: E402
from aidesk.desks.base import roster      # noqa: E402
from aidesk.desks.radar import Radar      # noqa: E402
from aidesk.market.feed import Feed       # noqa: E402
from aidesk.types import Features         # noqa: E402


def feat(sym: str = "A/USDT", ts: float | None = None, mom: float = 0.004) -> Features:
    """Feature bien préfiltrée (mom15/vol/liq passent les préfiltres du radar)."""
    return Features(sym, 100.0, 99.9, 100.1, 6_000_000.0, mom, mom * 2, 2.0, 0.5,
                    True, 0.0 if ts is None else ts)


def scan_one(f: Features, ready: Radar, now: float) -> int:
    return len(ready.scan({f.symbol: f}, set(), now, 5_000_000.0))


@pytest.fixture()
def radar() -> Radar:
    return Radar(roster({"radar": ["T1"]}), fresh_s=300.0)


# 1) données fraîches -----------------------------------------------------------

def test_fraiche_est_utilisable(radar):
    now = time.time()
    f = feat(ts=now - 5)
    assert f.usable(now, 300.0) is True


def test_fraiche_traverse_les_pre_filtres_et_emet(radar):
    now = time.time()
    assert scan_one(feat(ts=now), radar, now) == 1


# 2) données périmées ----------------------------------------------------------

def test_perimee_pas_dentree(radar):
    now = time.time()
    f = feat(ts=now - 400)                     # au-delà de freshness_s = 300
    assert f.usable(now, 300.0) is False
    assert scan_one(f, radar, now) == 0


# 3) données absentes ----------------------------------------------------------

def test_symbole_absent_rien_est_emis(radar):
    now = time.time()
    sigs = radar.scan({"A/USDT": feat(ts=now)}, set(), now, 5_000_000.0)
    assert all(s.symbol != "Z/USDT" for s in sigs)
    assert radar.scan({}, set(), now, 5_000_000.0) == []


# 4) timestamp invalide (0/ négatif = inconnu ; epoch ancien = périmé ; skew futur) ---

@pytest.mark.parametrize("bad_ts", [0.0, -5.0])
def test_ts_inconnu_pas_dentree(radar, bad_ts):
    now = time.time()
    f = feat(ts=bad_ts)
    assert f.age(now) is None                 # impossible d'établir la fraîcheur
    assert f.usable(now, 300.0) is False
    assert scan_one(f, radar, now) == 0


def test_ts_epoch_ancien_est_perime_pas_dentree(radar):
    now = time.time()
    f = feat(ts=1.0)                          # 1970 : âge gigantesque mais calculable
    assert f.age(now) is not None and f.age(now) > 300.0
    assert f.usable(now, 300.0) is False      # classification : PÉRIMÉE, pas inconnue
    assert scan_one(f, radar, now) == 0


def test_ts_futur_exageré_pas_dentree(radar):
    now = time.time()
    f = feat(ts=now + 1_000_000.0)
    assert f.usable(now, 300.0) is False
    assert scan_one(f, radar, now) == 0


# 5) fraîcheur inconnue (Features reconstruites à l'ancienne, ex: restore) ------

def test_features_anciennes_sans_ts_pas_usable(radar):
    now = time.time()
    old = Features("A/USDT", 100.0, None, None, 0.0, 0.0, 0.0, 0.0, 0.0)  # style restore
    assert old.ts == 0.0
    assert old.usable(now, 300.0) is False
    assert scan_one(old, radar, now) == 0


def test_fresh_false_explicite_bloque_meme_si_ts_frais(radar):
    now = time.time()
    f = feat(ts=now)
    f.fresh = False
    assert f.usable(now, 300.0) is False
    assert scan_one(f, radar, now) == 0


# 6) source indisponible + fallback offline -------------------------------------

def test_fallback_offline_produit_des_observations_datablees():
    feed = Feed(offline=True)                 # aucune source réseau
    feats = feed.refresh(8)
    now = time.time()
    assert feed.offline is True
    assert feats and len(feats) >= 6
    for f in feats.values():
        assert f.ts > 0
        assert f.age(now) is not None and f.age(now) < 300


# 7) cohérence avec le mode offline (le radar reste opérant en démo) -------------

def test_offline_features_utilisables_par_le_radar():
    feed = Feed(offline=True)
    feats = feed.refresh(8)
    now = time.time()
    usable = {s: f for s, f in feats.items() if f.usable(now, 300.0)}
    assert len(usable) == len(feats)          # aucune feature offline invisible
    r = Radar(roster({"radar": ["T1"]}), fresh_s=300.0)
    for _ in range(3):                        # plusieurs rotations ; l'émission dépend du RNG
        r.scan(dict(usable), set(), now, 0.0)
    assert r.signals_emitted >= 1


# 8) configuration du seuil ------------------------------------------------------

def test_seuil_defaut_et_chargement_yaml(tmp_path):
    assert Settings().freshness_s == 300.0
    cfg = tmp_path / "desk.yaml"
    cfg.write_text("desks:\n  risk:\n    agents: [R]\nfeed:\n  freshness_s: 123\n",
                   encoding="utf-8")
    s, _ = Settings.load(str(cfg))
    assert s.freshness_s == 123.0
    # yaml sans section feed → défaut 300 (rétro-compatibilité)
    cfg2 = tmp_path / "d2.yaml"
    cfg2.write_text("desks:\n  risk:\n    agents: [R]\n", encoding="utf-8")
    s2, _ = Settings.load(str(cfg2))
    assert s2.freshness_s == 300.0
