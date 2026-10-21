from __future__ import annotations

import pytest

from aidesk import llm
from aidesk.config import Matrix
from aidesk.desks.research import Research
from aidesk.types import Features, Signal

MATRIX = Matrix()


def feats(**kw):
    base = dict(symbol="T/USDT", last=100.0, bid=99.99, ask=100.01,
                quote_volume_24h=60_000_000.0, mom_15m=0.003, mom_1h=0.01,
                vol_surprise=2.2, range_pct=1.0)
    base |= kw
    return Features(**base)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(llm, "critique", lambda f, t: None)


class FixedStore:
    def __init__(self):
        self.list_ = []

    def add_decision(self, d):
        self.list_.append(d)


def make_research():
    return Research([_A("MEMORY"), _A("MEMORY-2")], MATRIX, FixedStore())


class _A:
    def __init__(self, name):
        self.name = name


def test_signal_bon_momentum_passe():
    r = make_research()
    d = r.decide(Signal(symbol="T/USDT", agent="SCOUT", ts=0.0, features=feats()),
                 now=0.0)
    assert d.verdict is True
    assert d.agg == pytest.approx(0.7875, abs=0.002)
    assert d.thesis.startswith("THÈSE")


def test_volume_insuffisant_refuse():
    r = make_research()
    d = r.decide(Signal(symbol="T/USDT", agent="SCOUT", ts=0.0,
                        features=feats(vol_surprise=1.2)), now=0.0)
    assert d.verdict is False


def test_overextension_casse_le_verdict():
    r = make_research()
    d = r.decide(Signal(symbol="T/USDT", agent="SCOUT", ts=0.0,
                        features=feats(mom_1h=0.09)), now=0.0)
    assert d.scores["overextension"] < 0.5
    assert d.verdict is False


def test_rotation_research_agents():
    r = make_research()
    d1 = r.decide(Signal(symbol="A/USDT", agent="SCOUT", ts=0.0, features=feats()),
                  now=0.0)
    d2 = r.decide(Signal(symbol="B/USDT", agent="SCOUT", ts=0.0, features=feats()),
                  now=1.0)
    assert (d1.agent, d2.agent) == ("MEMORY", "MEMORY-2")
