from __future__ import annotations

import pytest

from aidesk.config import Settings
from aidesk.desks.head import HeadOffice
from aidesk.desks.base import Agent


def test_promotion_meilleur_agent():
    a = Agent(name="AGOOD", desk="execution")
    for _ in range(6):
        a.credit_win(0.05)
    head = HeadOffice(Settings(), store=None)
    head.store = type("S", (), {"add_event": staticmethod(lambda *a, **k: None)})()
    head.review([a], now=100.0)
    assert a.budget == pytest.approx(1.2)
    assert head.promotions == 1
    assert len(head.logs) == 1 and "PROMOTION" in head.logs[0]


def test_licenciement_pire_agent():
    bad = Agent(name="ABAD", desk="research")
    for _ in range(6):
        bad.credit_loss(-0.02)
    head = HeadOffice(Settings(), store=None)
    head.store = type("S", (), {"add_event": staticmethod(lambda *a, **k: None)})()
    # le cooldown de licenciement vaut cooldown_h × 3600 s : on va au-delà
    head.review([bad], now=100_000.0)
    assert head.firings == 1
    assert bad.rev == "v2"
    assert bad.wins == 0 and bad.losses == 0 and bad.trades_credited == 0
    # cooldown : pas de re-licenciement immédiat
    head.review([bad], now=100_200.0)
    assert head.firings == 1
