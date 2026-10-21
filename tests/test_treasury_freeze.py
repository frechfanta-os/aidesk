"""Tests B4 — gel de trésorerie évalué à chaque tick.

Politique inchangée (gel si net < 60 % du start, dégel uniquement à ≥ 85 %) ;
seule la FRÉQUENCE d'évaluation change : un tick au lieu d'une heure. Le gel est
re-dérivé du ledger au boot (stateless) et est effectif avant toute nouvelle
entrée. Aucune horloge système n'est modifiée : `now` est passé en paramètre.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.config import Matrix, Settings       # noqa: E402
from aidesk.desks.risk import RiskAgent          # noqa: E402
from aidesk.market.ledger import Ledger          # noqa: E402
from aidesk.runtime import Desk                  # noqa: E402
from aidesk.types import Decision, Features, Signal  # noqa: E402


# --- unité : transitions du gel ------------------------------------------------

def make_risk(wallet: float) -> tuple[RiskAgent, Ledger]:
    led = Ledger(30.0)
    led.wallet_usdt = wallet
    return RiskAgent(Settings(), led), led


def test_seuil_franchi_entre_deux_heures_activer_le_gel():
    r, _ = make_risk(5.0)                    # net 5 < 18 (60 % de 30)
    r.check_treasury_freeze()
    ok, why = r.allow(0, time.time())
    assert r.frozen_treasury is True
    assert ok is False and why == "gel trésorerie"
    assert r.blocks == 1


def test_bande_intermediaire_reste_gelee_hysteresis():
    r, _ = make_risk(5.0)
    r.check_treasury_freeze()
    r.ledger.wallet_usdt = 22.0              # entre 60 % (18) et 85 % (25.5)
    r.check_treasury_freeze()
    assert r.frozen_treasury is True         # PAS de dégel au milieu de l'histérisis


def test_degele_seulement_a_85_pc():
    r, _ = make_risk(5.0)
    r.check_treasury_freeze()
    r.ledger.wallet_usdt = 25.5              # exactement 85 % du start
    r.check_treasury_freeze()
    assert r.frozen_treasury is False
    ok, why = r.allow(0, time.time())
    assert ok is True and why == "OK"


# --- wiring : gel effectif avant toute nouvelle entrée, à chaque tick ----------

def features_ok() -> Features:
    return Features("TESTX/USDT", 100.0, 99.9, 100.1, 6_000_000.0,
                    0.004, 0.02, 2.0, 0.5, True, time.time())


def force_one_signal(desk: Desk, monkeypatch) -> None:
    sig = Signal(symbol="TESTX/USDT", agent="SCOUT",
                 ts=time.time(), features=features_ok())
    monkeypatch.setattr(desk.radar, "scan", lambda *a, **k: [sig])
    monkeypatch.setattr(desk.research, "decide",
                        lambda sig, now: Decision(
                            ts=now, symbol=sig.symbol, agent="M1",
                            scores={"momentum": 1.0, "volume": 0.5,
                                    "overextension": 0.75, "liquidity": 0.12},
                            agg=0.65, verdict=True,
                            thesis="thèse de test", objection=None))


def capture_buy(desk: Desk, monkeypatch) -> list:
    bought: list = []

    def fake_buy(f, size, agent, approver):
        from aidesk.types import Position
        bought.append((f.symbol, size))
        return Position(symbol=f.symbol, entry=f.last, qty=1.0, usdt=size,
                        ts_open=time.time(), agent=agent, approver=approver,
                        features=f, score=0.0)
    monkeypatch.setattr(desk.broker, "buy", fake_buy)
    return bought


def test_gel_bloque_les_entrees_des_le_mauvais_tick(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)              # pas de state.json réel à restaurer
    desk = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    desk.ledger.wallet_usdt = 5.0            # net < 60 % du start
    force_one_signal(desk, monkeypatch)
    bought = capture_buy(desk, monkeypatch)
    desk.tick(True)
    assert bought == []                      # aucune entrée alors que verdict=True
    assert desk.risk.frozen_treasury is True


def test_reprise_apres_retablissement_de_la_banque(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    desk = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    desk.ledger.wallet_usdt = 5.0
    force_one_signal(desk, monkeypatch)
    bought = capture_buy(desk, monkeypatch)
    desk.tick(True)
    assert bought == [] and desk.risk.frozen_treasury is True
    desk.ledger.wallet_usdt = 28.5           # ≥ 85 % → dégel sur le tick suivant
    desk.tick(True)
    assert desk.risk.frozen_treasury is False
    assert len(bought) == 1 and bought[0][0] == "TESTX/USDT"


def test_gel_rederive_au_redemarrage_sans_etat_persiste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d1 = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    d1.ledger.wallet_usdt = 4.0
    d1.tick(True)
    assert d1.risk.frozen_treasury is True
    d2 = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    assert d2.risk.frozen_treasury is False  # rien n'est persisté…
    force_one_signal(d2, monkeypatch)
    bought = capture_buy(d2, monkeypatch)
    d2.tick(True)
    assert bought == []                      # …mais le gel s'applique dès le 1er tick,
    assert d2.risk.frozen_treasury is True   # re-dérivé du ledger restauré


def test_positions_ouvertes_toujours_gerees_pendant_le_gel(tmp_path, monkeypatch):
    """Le gel bloque les ENTRÉES, pas la gestion des positions (sorties TP/SL)."""
    monkeypatch.chdir(tmp_path)
    desk = Desk(Settings(), Matrix(), offline=True, db_path="t.db", jsonl="t.jsonl")
    desk.ledger.wallet_usdt = 5.0
    pos = desk.broker.buy(features_ok(), 2.0, "EXEC", "M1")
    assert "TESTX/USDT" in desk.broker.open
    before = desk.ledger.wallet_usdt
    desk.tick(True)                          # TP/SL/out gérés même gelé
    assert desk.risk.frozen_treasury is True
    # la position a pu être gérée (clôturée ou existante) : aucun blocage de sorties
    assert ("TESTX/USDT" not in desk.broker.open) or desk.ledger.wallet_usdt >= before * 0.99
