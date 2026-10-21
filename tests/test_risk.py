from __future__ import annotations

import pytest

from aidesk.config import Settings
from aidesk.desks.risk import RiskAgent
from aidesk.market.ledger import Ledger


@pytest.fixture()
def risk_env():
    s = Settings()
    l = Ledger(s.start_usdt)
    return s, l, RiskAgent(s, l)


def test_position_cap_blocks(risk_env):
    s, _, r = risk_env
    now = 0.0
    for i in range(s.max_open_positions):
        ok, why = r.allow(i, now)
        assert ok is True
        r.note_entry(now)
    ok, why = r.allow(s.max_open_positions, now)
    assert ok is False and "max positions" in why


def test_blocks_after_entries_per_hour(risk_env):
    s, _, r = risk_env
    now = 10.0
    for i in range(s.max_entries_per_hour):
        assert r.allow(0, now + i)[0] is True
        r.note_entry(now + i)
    ok, why = r.allow(0, now + 60)
    assert ok is False and "entrées/h" in why
    # fenêtre glissante : après 1 h les entrées expirent
    assert r.allow(0, now + 3601)[0] is True


def test_daily_loss_stop_freezes_day(risk_env):
    s, _, r = risk_env
    threshold = s.start_usdt * s.daily_loss_stop        # −10 % de 30 = −3
    r.on_close(threshold)
    ok, why = r.allow(0, 5.0)
    assert ok is False and "journalier" in why
    # nouvelle journée (UTC) → reset
    r.day = "2000-01-01"
    ok, why = r.allow(0, 5.0)
    assert ok is True


def test_treasury_freeze_and_unfreeze(risk_env):
    s, l, r = risk_env
    l.wallet_usdt = s.start_usdt * s.freeze_below - 1.0   # sous le plancher
    r.check_treasury_freeze()
    ok, why = r.allow(0, 0.0)
    assert ok is False and "trésorerie" in why
    l.vault_usdt = s.start_usdt * 2                       # net remonte > 0.85 × start
    r.check_treasury_freeze()
    assert r.frozen_treasury is False


def test_size_for_budget_multiplier(risk_env):
    s, _, r = risk_env
    base = s.start_usdt * s.max_position_fraction
    assert r.size_for(1.0) == pytest.approx(base)
    assert r.size_for(1.5) == pytest.approx(base * 1.5)
